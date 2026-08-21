"""Type-driven collapse of call subtrees, and its inverse.

Imports only the module under test, awl.elide for the folded input it consumes,
the contracts package, and the two AST/JSON converters.
"""

import ast
import json
from typing import Any

import pytest
from ast2json import ast2json
from json2ast import json2ast

from awl.collapse import collapse, expand
from awl.elide import elide

SOURCE = "charge(ChargeParam(target_voltage=4.2, c_rate=0.23))\n"

TYPES: dict[str, Any] = {
    "ChargeParam": {
        "identity": {
            "iri": "https://w3id.org/awl/py/battery.params/ChargeParam",
            "symbol": "ChargeParam",
            "scheme": "py",
        },
        "declaredTypes": ["ex:ChargeParam"],
        "fields": [
            {
                "name": "target_voltage",
                "isLink": False,
                "isMany": False,
                "declarationForm": "plain",
            },
            {"name": "c_rate", "isLink": False, "isMany": False, "declarationForm": "plain"},
        ],
    }
}
RESOLVED = {"ChargeParam": "ChargeParam"}


def _folded(source=SOURCE):
    """The input the collapse actually receives: keywords already folded."""
    return elide(ast2json(ast.parse(source)), profile="workflow")


def _collapsed(doc):
    """Return the collapsed constructor node.

    Identified by `type` holding a list: a syntax node names one type, a
    collapsed constructor names its class and any co-types.
    """
    return _find(doc, lambda item: isinstance(item.get("type"), list))


def _find(doc, predicate):
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


def test_a_resolved_constructor_becomes_one_typed_node():
    out = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    node = _find(out, lambda item: "ex:ChargeParam" in (item.get("type") or []))
    assert node is not None
    assert node["target_voltage"] == 4.2
    assert node["c_rate"] == 0.23
    assert "keywordArguments" not in node, "the plumbing is gone"


def test_the_property_namespace_is_the_resolvable_iri():
    """A declared type is a CURIE against a prefix this package does not own.

    Using it as the namespace produces ex:ChargeParam#target_voltage, which
    validates and joins with nothing.
    """
    out = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    node = _find(out, lambda item: "@context" in item)
    assert node["@context"]["@vocab"].startswith("https://w3id.org/awl/")
    assert node["type"] == ["ChargeParam", "ex:ChargeParam"], "class name first, then co-types"


def test_a_type_without_a_declared_iri_falls_back_to_the_minted_one():
    """Tier 2 has no declared IRI, and must still collapse to something typed."""
    types: dict[str, Any] = {"ChargeParam": {**TYPES["ChargeParam"], "declaredTypes": []}}
    out = collapse(_folded(), types=types, resolved=RESOLVED)
    node = _find(out, lambda item: "type" in item)
    assert node["type"] == ["ChargeParam"], "the class name alone still identifies it"


def test_an_unresolved_callee_is_left_alone():
    """A wrong type is worse than none, so an unresolved name stays a call."""
    out = collapse(_folded(), types=TYPES, resolved={})
    assert _find(out, lambda item: "type" in item) is None
    assert _find(out, lambda item: item.get("_type") == "Call") is not None


def test_an_undeclared_keyword_prevents_collapse():
    """Inventing a property from an unknown keyword would fabricate semantics."""
    out = collapse(
        _folded("ChargeParam(target_voltage=4.2, not_a_field=1)\n"),
        types=TYPES,
        resolved=RESOLVED,
    )
    assert _find(out, lambda item: "type" in item) is None


def test_the_faithful_profile_also_collapses():
    """Folding is reversible, so every profile folds and the collapse can fire
    where it matters most: the one that regenerates code.
    """
    out = collapse(elide(ast2json(ast.parse(SOURCE)), profile="ast"), types=TYPES, resolved=RESOLVED)
    assert _find(out, lambda item: "type" in item) is not None


def test_a_document_with_no_folded_keywords_is_left_alone():
    """Nothing to key on, so nothing is invented."""
    doc = {"_type": "Call", "func": {"_type": "Name", "id": "ChargeParam"}, "args": []}
    assert collapse(doc, types=TYPES, resolved=RESOLVED) == doc


def test_a_nested_call_inside_an_uncollapsed_one_still_collapses():
    """Refusing to collapse the outer call must not stop the walk."""
    out = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    outer = _find(out, lambda item: item.get("func", {}).get("id") == "charge")
    assert outer is not None, "charge is not a known type, so it stays a call"
    assert _find(outer, lambda item: "ex:ChargeParam" in (item.get("type") or [])) is not None


def test_collapse_is_reversible():
    """Collapse, expand, unparse: back to the source that produced it."""
    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED, keep_spans=True)
    restored = ast.unparse(ast.fix_missing_locations(json2ast(expand(collapsed))))
    assert restored.strip() == SOURCE.strip()


def test_an_edit_made_in_the_form_survives_expansion():
    """The editor flow end to end: dict, edit, expand, unparse."""
    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED)

    edited = json.loads(json.dumps(collapsed))  # as a form would return it
    node = _collapsed(edited)
    node["target_voltage"] = 4.1

    out = ast.unparse(ast.fix_missing_locations(json2ast(expand(edited))))
    assert "target_voltage=4.1" in out
    assert "c_rate=0.23" in out, "the untouched field is unharmed"


def test_the_collapsed_node_is_a_flat_editable_dict():
    """What a schema-driven form consumes, without a nested AST to navigate.

    Flatness is the property: a form binds an input to `target_voltage`, not to
    `keywords[0].value.value`.
    """
    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    node = _find(collapsed, lambda item: "type" in item)
    fields = {key: value for key, value in node.items() if key not in ("@context", "type", "span", "order")}
    assert fields == {"target_voltage": 4.2, "c_rate": 0.23}
    assert all(isinstance(value, float) for value in fields.values()), "scalars, not subtrees"


def test_the_span_is_carried_so_a_patch_can_be_applied_in_place():
    """Opt-in: needed to patch the file in place, not to regenerate code."""
    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED, keep_spans=True)
    node = _find(collapsed, lambda item: "type" in item)
    line, col, end_line, end_col = node["span"]
    assert (line, end_line) == (1, 1)
    assert SOURCE[col:end_col].startswith("ChargeParam(")


def test_a_node_naming_no_local_class_cannot_be_expanded():
    """Guards the reversibility contract itself.

    A CURIE is emitted verbatim and names no local class, so there is no name
    to write. Guessing one would be worse than refusing.
    """
    with pytest.raises(ValueError, match="no local class"):
        expand({"type": "ex:ChargeParam", "target_voltage": 4.2})


def test_expanding_a_plain_document_changes_nothing():
    doc = elide(ast2json(ast.parse("x = 1\n")), profile="workflow")
    assert ast.unparse(ast.fix_missing_locations(json2ast(expand(doc)))) == "x = 1"


def test_the_collapsed_node_survives_the_rdf_projection():
    """The point of the embedded context.

    Without it the keyword names are unmapped terms, and JSON-LD drops them:
    the constructor renders as an empty blank node with its arguments gone.
    """
    from rdflib import Graph

    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    node = _find(collapsed, lambda item: "type" in item)
    graph = Graph()
    graph.parse(data=json.dumps(node), format="json-ld")
    predicates = {str(predicate) for _, predicate, _ in graph}
    assert any(predicate.endswith("target_voltage") for predicate in predicates), predicates
    assert any(predicate.endswith("c_rate") for predicate in predicates), predicates


def test_the_projected_values_are_the_ones_written():
    from rdflib import Graph

    collapsed = collapse(_folded(), types=TYPES, resolved=RESOLVED)
    node = _find(collapsed, lambda item: "type" in item)
    graph = Graph()
    graph.parse(data=json.dumps(node), format="json-ld")
    values = {str(object_) for _, _, object_ in graph}
    assert "4.2" in values and "0.23" in values


def test_the_input_document_is_not_mutated():
    doc = _folded()
    before = json.dumps(doc)
    collapse(doc, types=TYPES, resolved=RESOLVED)
    assert json.dumps(doc) == before


def test_the_compact_editor_form_is_class_name_plus_data():
    """The target shape: no AST plumbing around a constructor.

    A document-level context supplies the class term, so the node itself is
    just what it is and what it holds.
    """
    from awl.compact import encode

    types: dict[str, Any] = {"ChargeParam": {**TYPES["ChargeParam"], "declaredTypes": []}}
    doc = collapse(
        elide(ast2json(ast.parse(SOURCE)), profile="ast"),
        types=types,
        resolved=RESOLVED,
        embed_context=False,
    )
    node = _collapsed(encode(doc))
    assert node == {"type": ["ChargeParam"], "target_voltage": 4.2, "c_rate": 0.23}


def test_that_form_regenerates_the_original_python():
    """The whole point: export, hold as JSON, regenerate."""
    from awl.compact import decode, encode

    types: dict[str, Any] = {"ChargeParam": {**TYPES["ChargeParam"], "declaredTypes": []}}
    doc = collapse(
        elide(ast2json(ast.parse(SOURCE)), profile="ast"),
        types=types,
        resolved=RESOLVED,
        embed_context=False,
    )
    restored = ast.unparse(ast.fix_missing_locations(decode(encode(doc))))
    assert restored.strip() == SOURCE.strip()


def test_editing_the_json_changes_the_regenerated_python():
    """Edit a field as plain JSON, with no knowledge of the syntax tree."""
    from awl.compact import decode, encode

    types: dict[str, Any] = {"ChargeParam": {**TYPES["ChargeParam"], "declaredTypes": []}}
    compact = encode(
        collapse(
            elide(ast2json(ast.parse(SOURCE)), profile="ast"),
            types=types,
            resolved=RESOLVED,
            embed_context=False,
        )
    )
    edited = json.loads(json.dumps(compact))
    node = _collapsed(edited)
    node["target_voltage"] = 4.1

    out = ast.unparse(ast.fix_missing_locations(decode(edited)))
    assert "target_voltage=4.1" in out
    assert "c_rate=0.23" in out, "the untouched field is unharmed"


def test_the_class_term_resolves_through_the_document_context():
    """Dropping the embedded context must not cost the RDF its IRI."""
    from rdflib import Graph

    from awl.context import build_context

    types: dict[str, Any] = {"ChargeParam": {**TYPES["ChargeParam"], "declaredTypes": []}}
    doc = collapse(
        elide(ast2json(ast.parse(SOURCE)), profile="ast"),
        types=types,
        resolved=RESOLVED,
        embed_context=False,
    )
    node = _find(doc, lambda item: "type" in item)
    graph = Graph()
    graph.parse(
        data=json.dumps({"@context": build_context(list(types.values()))["@context"], **node}),
        format="json-ld",
    )
    minted = TYPES["ChargeParam"]["identity"]["iri"]
    assert any(str(object_) == minted for _, _, object_ in graph), "the bare term resolved to the minted IRI"
