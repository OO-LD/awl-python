"""
ast_annotation.py
======================

Traverse a Python abstract‑syntax tree (AST) that has already been serialised
into plain Python data structures (nested ``dict`` / ``list`` / primitives) and
build a *flater* annotation alongside it.  The resulting annotation simplifies

* Capital‑ised **constructor** calls, e.g. ClassA(a=1)

Everything else in the AST is kept as is.

Setting ``parsable=True`` keeps the "parsability of the AST
Setting ``parsable=False``forces *slim* notation in which the original
 AST fields such as ``_type`` or ``func`` are removed, the AST loses parsability


The entry point is AstAnnotation.parse(source), returns the AST dictionary of source with said anotations
"""

import json
from awl.core import AstSerialization

__all__ = [
    "ASTNotAModule",
    "AstAnnotation",
]


class ASTNotAModule(Exception):
    """Raised when the root node of the parsed object is **not** an ast.Module."""


class AstAnnotation(AstSerialization):
    """Annotate a *json‑serialisable* AST produced by
    :class:`awl.core.AstSerialization`.

    Parameters
    ----------
    parsable : bool, default ``False``
        When *False* the resulting annotation uses a shorter, *slim* notation in
        which keys like (``_type``, ``func``, etc.) are stripped.
    """

    def __init__(self, parsable: bool = False) -> None:
        super().__init__()
        self.parsable = parsable
        # self.annotateAST()

    def parse(self, source: str) -> dict:
        """Parse *source*, annotate the resulting AST and return the modified"""
        super().parse(source)
        self.annotate_ast()
        return self.ast_dict

    def annotate_ast(self) -> None:
        """Validate the root node and start annotation walk.
        Raises
        ------
        ASTNotAModule
            If the parsed tree does **not** start with an ``ast.Module`` node.
        """
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
            #print(f"Path: {path} -> Value: {node}")
            pass

        # ------------------------------------------------------------------ #
        # 2.Collapse handles the replacement logic to from leaf to "stem"
        # ------------------------------------------------------------------ #

        # This checks for the class constructor syntax in AST
        # e.g "value": {"_type": "Call","args": [],"func": {"_type": "Name","id": "ClassA"}
        if isinstance(node, dict):
            if (
                    node.get("_type") == "Call" # A Constructor is a call
                    and node.get("func", {}).get("_type") == "Name" # A Constructor is a call of type Name
                    and (fid := node.get("func", {}).get("id"))  # fid is None if the path is missing and hence False
                    and fid[0].isupper()  # only runs if fid is truthy, wont give TypeError/IndexError
            ):
                ctor_node = AstAnnotation._get_from_path(self.ast_dict,path)

                ctor_node["__class_name__"]= fid
                # self.ast_dict["__class_name__"] = fid
                # print (fid)

                for kw_node in node["keywords"]:
                    if isinstance(kw_node, dict):
                        if kw_node.get("_type") == "keyword":
                            ctor_node[kw_node["arg"]] = self._val(kw_node["value"])

                if self.parsable == False:
                    # slim notation
                    ctor_node = AstAnnotation.slim_notation(ctor_node)



                        # ------------------------------------------------------------------ #
    # Value helper
    # ------------------------------------------------------------------ #
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
            #todo currently f(a=t) and f(a="t") have same annotation, think about if this can lead to problems
            t = node.get("_type")
            ctor = node.get("__class_name__")
            # f(a=1) :"value": {"_type": "Constant","value": 1}
            if t == "Constant":
                return node["value"]
            # f(a=t) : "value": {"_type": "Name","id": "t"}
            if t == "Name":
                return node["id"]
            #f(a = U.V) : "value": {"_type": "Attribute","attr": "V","value": {"_type": "Name","id": "U"}}
            if t == "Attribute":
                return AstAnnotation._attr_to_str(node)
            if ctor:
                return AstAnnotation.slim_notation(node.copy())
        return None

    # ------------------------------------------------------------------ #
    # Attribute -> dotted string
    # ------------------------------------------------------------------ #
    @staticmethod
    def _attr_to_str(node: dict) -> str:
        """Flatten a chain of ``Attribute``/``Name`` nodes into ``"U.V"``."""
        # f(a = U.V) : "value": {"_type": "Attribute","attr": "V","value": {"_type": "Name","id": "U"}}
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
    def _get_from_path(
            node: list | dict | object, path: list
    ) -> list | dict | object:
        """Return the sub‑node referenced by *path*."""
        for key in path:
            node = node[key]
        return node
    @staticmethod
    def _dump_from_path(
        node: list | dict | object, path: list
    ) -> str:
        """Pretty JSON dump of the sub‑node at *path* (debug helper)."""
        node = AstAnnotation._get_from_path(node, path)
        res = json.dumps(node, indent=4)
        return res
    @staticmethod
    def slim_notation(node: list | dict | object) ->  list | dict | object:
        """pops the unnecessary parameters of a constructor and returns slim notation node"""
        for k in ("_type", "args", "func", "keywords"):
            node.pop(k, None)
        return node


if __name__ == "__main__":
    test = AstAnnotation(parsable=False)
    # demo_src = """ClassA(a=1, b='b', c=ClassB(d=False))"""
    # demo_src = (
    #     "battery = Battery(nominal_capacity=Capacity(value=4, unit=U.ampere_hour),"
    #     "min_operating_voltage=Voltage(value=4, unit=U.V))"
    # )

    demo_src = (
        "battery = Battery(nominal_capacity=Capacity(value=4, unit=U.ampere_hour),min_operating_voltage=Voltage(value=4, unit=U.V))\n"
        "while(i<3):\n"
        "   battery.discharge(ChargeParam(target_voltage=Voltage(value=4, unit=U.V),current=Current(value=2, unit=U.A)))\n"
        "   battery.charge(ChargeParam(target_voltage=Voltage(value=4, unit=U.V),current=Current(value=2, unit=U.A)))\n"
        "   i+=1"
    )


    test.parse(demo_src)
    print(test.dumps(format="json"))

    # a = ["body", 0, "value", "keywords", 1, "value"]
    # a = []
    # print(test._dump_from_path(test.ast_dict, a))

    # print(dbg.dumps(format="json"))
