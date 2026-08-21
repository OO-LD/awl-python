"""Profile-driven cutoff: ordering, keyword folding and elision.

Imports only the module under test, the vocabulary, the contracts package and
the two AST/JSON converters.
"""

import ast
import json

import pytest
from ast2json import ast2json
from json2ast import json2ast

from awl import contracts
from awl.elide import elide

TIER2 = contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py"


def _find(doc, predicate):
    """Return the first node satisfying *predicate*, depth first."""
    if isinstance(doc, dict):
        if predicate(doc):
            return doc
        for value in doc.values():
            found = _find(value, predicate)
            if found:
                return found
    elif isinstance(doc, list):
        for item in doc:
            found = _find(item, predicate)
            if found:
                return found
    return None


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_ast_profile_round_trips(path):
    """Compared against unparse(tree), not against the file.

    ast.unparse normalises formatting and discards comments, so comparing to
    source would test the unparser rather than this stage. Byte-level source
    fidelity belongs to write-back, by patching spans.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    restored = json2ast(elide(ast2json(tree), profile="ast"))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


def test_a_named_argument_never_becomes_positional():
    """The regression this design exists to prevent.

    Splicing a keyword's value into its parent returns the value and discards
    the name, which is a semantic change and also leaves the collapse with
    nothing to match on.
    """
    source = "charge(ChargeParam(target_voltage=4.2, c_rate=0.23))\n"
    doc = elide(ast2json(ast.parse(source)), profile="ast")
    restored = ast.unparse(ast.fix_missing_locations(json2ast(doc)))
    assert "target_voltage=4.2" in restored
    assert "ChargeParam(4.2" not in restored


@pytest.mark.parametrize("profile", ["ast", "workflow", "provenance", "signature"])
def test_no_profile_loses_an_argument_name(profile):
    """At the reduced profiles the name moves, but it must never vanish."""
    source = "charge(ChargeParam(target_voltage=4.2, c_rate=0.23))\n"
    doc = elide(ast2json(ast.parse(source)), profile=profile)
    assert "target_voltage" in json.dumps(doc)
    assert "c_rate" in json.dumps(doc)


def test_statements_carry_a_contiguous_order():
    """The materialized index: rdf:rest*/rdf:first enumerates but cannot count."""
    doc = elide(ast2json(ast.parse(TIER2.read_text(encoding="utf-8"))), profile="workflow")
    procedure = _find(doc, lambda node: node.get("_type") == "FunctionDef")
    orders = [statement.get("order") for statement in procedure["body"]]
    assert orders == list(range(len(orders))), orders


def test_a_loop_body_is_ordered_too():
    """Ordering has to reach nested statement lists, not only the top level."""
    doc = elide(ast2json(ast.parse(TIER2.read_text(encoding="utf-8"))), profile="workflow")
    loop = _find(doc, lambda node: node.get("_type") == "While")
    assert [statement.get("order") for statement in loop["body"]] == [0, 1, 2]


def test_a_folded_keyword_keeps_its_name_and_is_marked_named():
    doc = elide(ast2json(ast.parse(TIER2.read_text(encoding="utf-8"))), profile="workflow")
    call = _find(doc, lambda node: node.get("func", {}).get("id") == "ChargeParam")
    assert set(call["keywordArguments"]) == {"target_voltage", "c_rate"}
    assert call["keywordArguments"]["target_voltage"]["argumentName"] == "target_voltage"
    assert call["keywordArguments"]["target_voltage"]["argumentIndex"] == -1, "-1 means named"
    assert "keywords" not in call, "folded, so the wrapper list is gone"


def test_the_ast_profile_does_not_fold():
    """Folding rewrites the call, so the round-trippable profile must not."""
    doc = elide(ast2json(ast.parse("f(x=1)\n")), profile="ast")
    call = _find(doc, lambda node: node.get("_type") == "Call")
    assert "keywordArguments" not in call
    assert call["keywords"][0]["arg"] == "x"


def test_positional_arguments_are_numbered_from_one():
    """0 is reserved for an implicit receiver, per the code property graph."""
    doc = elide(ast2json(ast.parse("f(a, b)\n")), profile="workflow")
    call = _find(doc, lambda node: node.get("_type") == "Call")
    assert [argument["argumentIndex"] for argument in call["args"]] == [1, 2]


def test_mixed_positional_and_named_arguments_stay_distinguishable():
    """The two orderings are separate: sibling slot against argument slot."""
    doc = elide(ast2json(ast.parse("f(a, x=1)\n")), profile="workflow")
    call = _find(doc, lambda node: node.get("_type") == "Call")
    assert call["args"][0]["argumentIndex"] == 1
    assert call["keywordArguments"]["x"]["argumentIndex"] == -1


def test_the_workflow_profile_is_smaller_than_ast():
    raw = ast2json(ast.parse(TIER2.read_text(encoding="utf-8")))
    sizes = {profile: len(json.dumps(elide(raw, profile=profile))) for profile in ("ast", "workflow", "signature")}
    assert sizes["workflow"] < sizes["ast"], sizes
    assert sizes["signature"] <= sizes["workflow"], sizes


def test_the_input_document_is_not_mutated():
    """The stages are total functions over plain data; sharing state between
    two profile runs would make the second depend on the first.
    """
    raw = ast2json(ast.parse(TIER2.read_text(encoding="utf-8")))
    before = json.dumps(raw)
    elide(raw, profile="workflow")
    assert json.dumps(raw) == before


def test_an_unknown_profile_raises():
    with pytest.raises(KeyError):
        elide({"_type": "Module"}, profile="invented")


def test_the_frontend_label_survives_elision():
    source = "x = a < b\n"
    doc = elide(ast2json(ast.parse(source)), profile="workflow", source=source)
    opaque = _find(doc, lambda node: node.get("parserTypeName") == "Compare")
    assert opaque is not None
    assert opaque["_type"] == "Call", "a neutral node type, with the label as a property"
    assert opaque["sourceText"] == "a < b", "the expression is kept as text, not lost"


def test_an_opaque_node_without_source_keeps_its_type_and_loses_its_text():
    """A real loss, stated rather than hidden: the pipeline must pass source."""
    doc = elide(ast2json(ast.parse("x = a < b\n")), profile="workflow")
    opaque = _find(doc, lambda node: node.get("parserTypeName") == "Compare")
    assert opaque["sourceText"] == ""


def test_a_multiline_opaque_node_keeps_every_line():
    source = "x = (a <\n     b)\n"
    doc = elide(ast2json(ast.parse(source)), profile="workflow", source=source)
    opaque = _find(doc, lambda node: node.get("parserTypeName") == "Compare")
    assert "a <" in opaque["sourceText"] and "b" in opaque["sourceText"]
