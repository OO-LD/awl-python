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


def test_decoder_populates_every_field_of_the_node():
    """Asserting the fields are present is version-independent; asserting the
    failure mode is not.

    The package supports 3.11 upward. A decoder that only copies present keys
    passes on 3.13, which returns 'b = 1' for a Module with no type_ignores,
    and raises AttributeError on 3.11. So the test pins the invariant rather
    than the symptom.
    """
    node = decode(encode(ast2json(ast.parse("b = 1"))))
    missing = [field for field in type(node)._fields if not hasattr(node, field)]
    assert not missing, f"decoder left {missing} unreconstructed"


def test_encoder_drops_empty_required_lists():
    """Otherwise the test above passes vacuously."""
    assert "type_ignores" not in encode(ast2json(ast.parse("b = 1")))
