import ast
import json

import yaml
from ast2json import ast2json
from json2ast import json2ast

from awl import jsonld_context


class ASTNotAModule(Exception):
    """Raised when the root node of the parsed object is **not** an ast.Module."""


class AstSerialization:
    def __init__(self, annotate: bool = False, backparsable: bool = False) -> None:
        """
        Initializes AstSerialization with parser options.

        Parameters
        ----------
        annotate : bool, default False
            If ``True``, annotates the AST tree
        backparsable : bool, default False
            If ``True``, AST tree is unparsable via self.unparse
            If ``False``, Annotations deletes that are required for unparsing,
             resulting in a neat tree
        """
        self.annotate = annotate
        self.backparsable = backparsable

    @staticmethod
    def del_keys(d: dict, keys: list) -> dict:
        for key in keys:
            if key in d:
                del d[key]
        for key, value in d.items():
            if isinstance(value, dict):
                AstSerialization.del_keys(value, keys)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        AstSerialization.del_keys(item, keys)
        return d

    @staticmethod
    def add_key(d: dict, k: str, v) -> dict:
        d[k] = v
        for key, value in d.items():
            if isinstance(value, dict):
                AstSerialization.add_key(value, k, v)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        AstSerialization.add_key(item, k, v)
        return d

    def parse(self, source: str) -> dict:
        ast_dict = ast2json(ast.parse(source))

        rm_keywords = [
            "col_offset",
            "end_col_offset",
            "end_lineno",
            "lineno",
            "type_comment",
            "n",
            "s",
            "kind",
            "ctx",
        ]

        ast_dict = self.del_keys(ast_dict, rm_keywords)  # remove annotations
        self.ast_dict = ast_dict

        if self.annotate:
            self.annotate_ast()

        return ast_dict

    def unparse(self, ast_dict: dict = None) -> str:
        ast_dict = self.add_key(ast_dict, "lineno", 0)  # needed to unparse
        ast_tree = json2ast(ast_dict)
        source = ast.unparse(ast_tree)
        return source

    def dumps(self, format="yaml") -> str:
        res = ""
        if format == "json":
            res = json.dumps(self.ast_dict, indent=4)
        elif format == "yaml":
            res = yaml.dump(self.ast_dict, indent=4)
        return res

    def annotate_ast(self) -> None:
        """Validate the root node and start annotation walk.
        Raises
        ------
        ASTNotAModule
            If the parsed tree does **not** start with an ``ast.Module`` node.
        """
        # todo add further veryfication
        if self.ast_dict.get("_type") != "Module":
            raise ASTNotAModule("root node is not a Module")
        self._walk_json_ast(self.ast_dict, path=None)

    def _walk_json_ast(self, node: list | dict | object, path: list) -> None:
        """Depth‑first traversal of *node* while keeping track of *path*.

        Parameters
        ----------
        node
            Current AST sub‑node (``dict``, ``list`` or scalar).
        path
            Accumulated list of keys / indices leading from the root to *node*.
        """

        if path is None:
            path = []
        # ------------------------------------------------------------------ #
        # 1.Recursive walk
        # ------------------------------------------------------------------ #
        elif isinstance(node, list):
            # print(f"Path: {path}")
            for index, item in enumerate(node):
                self._walk_json_ast(item, path + [index])

        if isinstance(node, dict):
            # print(f"Path: {path}")
            for key, value in node.items():
                self._walk_json_ast(value, path + [key])

        # Primitive leaf – nothing to do
        else:
            # print(f"Path: {path} -> Value: {node}")
            pass

        # ------------------------------------------------------------------ #
        # 2.Collapse handles the replacement logic to from leaf to "stem"
        # ------------------------------------------------------------------ #

        # This checks for the class constructor syntax in AST
        # e.g "value":
        # {"_type": "Call","args": [],"func": {"_type": "Name","id": "ClassA"}
        if isinstance(node, dict):
            if (
                node.get("_type") == "Call"  # A Constructor is a call
                and node.get("func", {}).get("_type")
                == "Name"  # A Constructor is a call of type Name
                and (
                    fid := node.get("func", {}).get("id")
                )  # fid is None if the path is missing and hence False
                and fid[0].isupper()  # only runs if fid is truthy,
                # wont give TypeError/IndexError
            ):
                ctor_node = AstSerialization._get_from_path(self.ast_dict, path)

                ctor_node["__class_name__"] = fid
                # self.ast_dict["__class_name__"] = fid
                # print (fid)

                for kw_node in node["keywords"]:
                    if isinstance(kw_node, dict):
                        if kw_node.get("_type") == "keyword":
                            ctor_node[kw_node["arg"]] = self._val(kw_node["value"])

                if self.backparsable is False:
                    # slim notation
                    ctor_node = AstSerialization.slim_notation(ctor_node)

    @staticmethod
    def _val(node: list | dict | object) -> object | None:
        """Convert AST *value* nodes into primitives or nested constructor annotations.

        Returns
        -------
        object | None
            * ``int``, ``str`` … for ``Constant`` nodes;
            * dotted ``str`` for ``Attribute`` chains;
            * nested constructor annotations (dict) for embedded calls;
            * ``None`` for values that are irrelevant / not serialisable.
        """

        if isinstance(node, dict):
            # todo currently f(a=t) and f(a="t") have same annotation,
            #  think about if this can lead to problems
            t = node.get("_type")
            ctor = node.get("__class_name__")
            # f(a=1) :"value": {"_type": "Constant","value": 1}
            if t == "Constant":
                return node["value"]
            # f(a=t) : "value": {"_type": "Name","id": "t"}
            if t == "Name":
                return node["id"]
            # f(a = U.V) : "value":
            # {"_type": "Attribute","attr": "V","value": {"_type": "Name","id": "U"}}
            if t == "Attribute":
                return AstSerialization._attr_to_str(node)
            if ctor:
                return AstSerialization.slim_notation(node.copy())
        return None

    # ------------------------------------------------------------------ #
    # Attribute -> dotted string
    # ------------------------------------------------------------------ #
    @staticmethod
    def _attr_to_str(node: dict) -> str:
        """Flatten a chain of ``Attribute``/``Name`` nodes into ``"U.V"``."""
        # f(a = U.V) : "value":
        # {"_type": "Attribute","attr": "V","value": {"_type": "Name","id": "U"}}
        parts: list[str] = []

        def walk(n):
            if n["_type"] == "Attribute":
                walk(n["value"])
                parts.append(n["attr"])
            elif n["_type"] == "Name":
                parts.append(n["id"])

        walk(node)
        return ".".join(parts)

    @staticmethod
    def _get_from_path(node: list | dict | object, path: list) -> list | dict | object:
        """Return the sub‑node referenced by *path*."""
        for key in path:
            node = node[key]
        return node

    @staticmethod
    def _dump_from_path(node: list | dict | object, path: list) -> str:
        """Pretty JSON dump of the sub‑node at *path* (debug helper)."""
        node = AstSerialization._get_from_path(node, path)
        res = json.dumps(node, indent=4)
        return res

    @staticmethod
    def slim_notation(node: list | dict | object) -> list | dict | object:
        """pops the unnecessary parameters of a constructor
        and returns slim notation node"""
        for k in ("_type", "args", "func", "keywords"):
            node.pop(k, None)
        return node

    def to_jsonld(self) -> dict:
        res = {"@context": jsonld_context.awl_context["@context"], **self.ast_dict}
        return res
