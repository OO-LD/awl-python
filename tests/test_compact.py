"""M9: the compact AST codec, which is the editor's model.

Imports only the module under test, the contracts package and ast2json.
"""

import ast
import json
from importlib.util import find_spec

import pytest
from ast2json import ast2json

from awl import contracts
from awl.compact import decode, encode

#: The elision stage is phase 4. The tests that compose with it are written now
#: and skip until it lands, because "M5 emits AstDoc and M9 consumes AstDoc" is
#: the property an earlier draft violated, and it must be asserted somewhere
#: rather than assumed.
needs_elide = pytest.mark.skipif(
    find_spec("awl.elide") is None,
    reason="M5 awl.elide is not implemented yet (phase 4)",
)

TIER2 = contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py"


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


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_round_trips_every_corpus_file(path):
    """Compared against unparse(tree), not against the source.

    ast.unparse normalises formatting and discards comments, so == source is
    unachievable and was measured failing on all 8 corpus files even with a
    correct implementation. Byte-level fidelity is M10's guarantee, delivered
    by patching spans rather than by regenerating.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    restored = decode(encode(ast2json(tree)))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


@needs_elide
def test_composes_with_the_elide_stage():
    """M5 emits AstDoc and M9 consumes AstDoc, so the pipeline can chain them.

    An earlier draft consumed live ast objects and silently could not.
    """
    from awl.elide import elide

    tree = ast.parse(TIER2.read_text(encoding="utf-8"))
    restored = decode(encode(elide(ast2json(tree), profile="ast")))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


@needs_elide
def test_the_orderings_survive_encoding():
    """M5's order is the query surface; losing it here would empty F7."""
    from awl.elide import elide

    doc = elide(ast2json(ast.parse(TIER2.read_text(encoding="utf-8"))), profile="workflow")
    assert '"order"' in json.dumps(encode(doc))


def test_the_orderings_are_carried_through_unchanged():
    """The same guarantee as above, asserted without M5.

    Hand-annotating the input is what makes this runnable in phase 2: the
    encoder must not decide which orderings are real, only carry them.
    """
    doc = ast2json(ast.parse("f(1, x=2)"))
    call = doc["body"][0]["value"]
    call["args"][0]["argumentIndex"] = 1
    call["keywords"][0]["value"]["argumentIndex"] = -1
    call["keywords"][0]["value"]["argumentName"] = "x"
    call["order"] = 0

    encoded = encode(doc)
    step = encoded["body"][0]["value"]
    assert step["order"] == 0
    assert step["args"][0] == {"c": 1, "argumentIndex": 1}
    assert step["keywords"][0]["value"] == {"c": 2, "argumentIndex": -1, "argumentName": "x"}


def test_an_ordering_does_not_force_a_literal_back_to_the_long_form():
    """A shorthand carries its ordering alongside; if it fell back to
    {"_": "Constant", ...} the compaction target would not be met.
    """
    doc = ast2json(ast.parse("f(1)"))
    doc["body"][0]["value"]["args"][0]["argumentIndex"] = 1
    assert "_" not in encode(doc)["body"][0]["value"]["args"][0]
