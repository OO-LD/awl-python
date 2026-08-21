"""M9: the compact AST codec, which is the editor's model.

Imports only the module under test, the contracts package and ast2json.
"""

import ast

from ast2json import ast2json

from awl.compact import decode, encode


def test_round_trips_a_single_assignment():
    doc = ast2json(ast.parse("b = a + 2"))
    restored = decode(encode(doc))
    assert ast.unparse(ast.fix_missing_locations(restored)) == "b = a + 2"
