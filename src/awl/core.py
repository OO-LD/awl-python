import ast
import json

import yaml
from ast2json import ast2json
from json2ast import json2ast

from awl import jsonld_context


class AstSerialization:
    def __init__(self):
        pass

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

    def to_jsonld(self) -> dict:
        res = {"@context": jsonld_context.awl_context["@context"], **self.ast_dict}
        return res
