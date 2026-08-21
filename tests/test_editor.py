"""The headless editing model: palette, edit operations, domain validation.

Imports only the module under test, awl.compact and the contracts package, and
needs no browser. Documents are produced by the encoder rather than hand-shaped,
so the addressing model is exercised against shapes that actually occur.
"""

import ast
from typing import Any

import jsonschema
import pytest
from ast2json import ast2json

from awl.compact import encode
from awl.editor import (
    add_step,
    delete_step,
    palette,
    reorder,
    set_literal,
    validate_domain,
)

DOMAIN = {
    "$defs": {
        "node": {
            "type": "object",
            "properties": {
                "_type": {"enum": ["Module", "FunctionDef", "If", "While", "Call"]},
                "callee": {"enum": ["battery.device.charge", "battery.device.rest"]},
            },
        }
    },
    "$ref": "#/$defs/node",
}

CHARGE_PARAM_SCHEMA = {
    "$id": "https://example.org/ChargeParam.schema.json",
    "title": "ChargeParam",
    "x-oold-instance-rdf-type": ["ex:ChargeParam"],
    "properties": {
        "target_voltage": {"type": "number", "x-format": "range"},
        "c_rate": {"type": "number"},
    },
}


def _compact(source):
    return encode(ast2json(ast.parse(source)))


def _at(doc, path):
    """Follow a mixed key/index path, which is how the editor addresses nodes."""
    node: Any = doc
    for key in path:
        node = node[key]
    return node


def test_the_palette_comes_from_the_schema_enums():
    """No hand-authored node definitions, and no vendor keyword."""
    by_kind = {(entry["kind"], entry["name"]) for entry in palette(DOMAIN)}
    assert ("construct", "While") in by_kind, "found through $defs nesting"
    assert ("callee", "battery.device.charge") in by_kind
    assert ("construct", "ClassDef") not in by_kind, "not permitted, so not offered"


def test_a_schema_declaring_nothing_yields_an_empty_palette():
    """A legitimate answer: this domain permits nothing."""
    assert palette({}) == []


def test_the_palette_has_no_duplicates():
    entries = palette(DOMAIN)
    assert len(entries) == len({(entry["kind"], entry["name"]) for entry in entries})


def test_a_typed_entry_carries_its_fields():
    """The non-obvious half: the palette entry already knows its form.

    Blockly needs a hand-written block definition per construct and React Flow
    a hand-written node component. Both fall out of schemas that already exist.
    """
    entries = palette(DOMAIN, type_schemas=[CHARGE_PARAM_SCHEMA])
    charge = next(entry for entry in entries if entry["name"] == "ChargeParam")
    assert charge["kind"] == "type"
    assert set(charge["fields"]) == {"target_voltage", "c_rate"}
    assert charge["declaredTypes"] == ["ex:ChargeParam"]


def test_a_typed_entry_keeps_the_widget_hint():
    """x-format lives in the schema, which is why there is no second artefact."""
    entries = palette(DOMAIN, type_schemas=[CHARGE_PARAM_SCHEMA])
    charge = next(entry for entry in entries if entry["name"] == "ChargeParam")
    assert charge["fields"]["target_voltage"]["x-format"] == "range"


def test_type_schemas_are_optional():
    """Without them the palette still lists legal constructs and callees."""
    assert palette(DOMAIN) == palette(DOMAIN, type_schemas=[])


def test_setting_a_literal_returns_both_the_document_and_the_span():
    """The document is real encoder output, not hand-shaped.

    An invented path would leave the addressing model unexercised. The real
    shape of `charge(ChargeParam(target_voltage=4.2))` nests Expr, Call, args,
    Call, keywords, and the path below is measured from it.
    """
    doc = _compact("charge(ChargeParam(target_voltage=4.2))\n")
    path = ["body", 0, "value", "args", 0, "keywords", 0, "value"]

    assert _at(doc, path) == {"literal": 4.2}, "the path is real"

    new_doc, edits = set_literal(doc, path=path, value=4.1, span={"start": 34, "end": 37})

    assert _at(new_doc, path) == {"literal": 4.1}
    assert edits == [{"start": 34, "end": 37, "text": "4.1"}]

    assert _at(doc, path) == {"literal": 4.2}, "the input is not mutated"


def test_the_returned_span_patch_is_what_the_writer_applies():
    """Closes the loop: the patch shape matches what write-back consumes.

    set_literal echoes the span it is given, so asserting only on the returned
    dict cannot tell a correct span from a wrong one. Applying it can.
    """
    source = "charge(ChargeParam(target_voltage=4.2))\n"
    start = source.index("4.2")
    doc = _compact(source)
    _, edits = set_literal(
        doc,
        path=["body", 0, "value", "args", 0, "keywords", 0, "value"],
        value=4.1,
        span={"start": start, "end": start + 3},
    )
    edit = edits[0]
    patched = source[: edit["start"]] + edit["text"] + source[edit["end"] :]
    assert patched == "charge(ChargeParam(target_voltage=4.1))\n"


def test_a_path_that_does_not_exist_is_refused():
    """A silent no-op edit is the worst outcome: the user sees a change that
    never reached the document.
    """
    with pytest.raises(KeyError, match="no node at"):
        set_literal(_compact("x = 1\n"), path=["body", 9, "value"], value=2, span={"start": 0, "end": 1})


def test_adding_a_step_returns_a_structural_patch():
    doc = _compact("charge(4.2)\n")
    node = _compact("rest(600)\n")["body"][0]
    new_doc, edits = add_step(doc, into=["body"], node=node)
    assert len(new_doc["body"]) == 2
    assert [step["order"] for step in new_doc["body"]] == [0, 1], "order is renumbered"
    assert edits[0]["kind"] == "structural", "must be routed through libcst"
    assert edits[0]["code"] == "rest(600)", "the patch carries what to insert"


def test_deleting_a_step_renumbers_the_rest():
    doc = _compact("charge(4.2)\nrest(600)\n")
    new_doc, edits = delete_step(doc, path=["body", 0])
    assert [step["order"] for step in new_doc["body"]] == [0]
    assert new_doc["body"][0]["value"]["func"] == {"var": "rest"}
    assert edits[0]["code"] == "charge(4.2)", "the patch names what was removed"


def test_reordering_updates_order_not_just_position():
    """order is the query surface. A reorder that moved list position without
    updating order would leave the RDF saying the opposite of the document.
    """
    doc = _compact("charge(4.2)\nrest(600)\n")
    new_doc, _ = reorder(doc, path=["body"], frm=0, to=1)
    assert [step["value"]["func"]["var"] for step in new_doc["body"]] == ["rest", "charge"]
    assert [step["order"] for step in new_doc["body"]] == [0, 1]


@pytest.mark.parametrize(
    "operation",
    [
        lambda doc, node: add_step(doc, into=["body"], node=node),
        lambda doc, node: delete_step(doc, path=["body", 0]),
        lambda doc, node: reorder(doc, path=["body"], frm=0, to=1),
    ],
    ids=["add", "delete", "reorder"],
)
def test_no_edit_mutates_its_input(operation):
    doc = _compact("charge(4.2)\nrest(600)\n")
    before = str(doc)
    operation(doc, _compact("hold(1)\n")["body"][0])
    assert str(doc) == before


@pytest.mark.parametrize(
    "operation",
    [
        lambda doc, node: add_step(doc, into=["body"], node=node),
        lambda doc, node: delete_step(doc, path=["body", 0]),
        lambda doc, node: reorder(doc, path=["body"], frm=0, to=1),
    ],
    ids=["add", "delete", "reorder"],
)
def test_every_structural_edit_reports_its_tier(operation):
    """The caller must never need to know which write-back mechanism applies."""
    doc = _compact("charge(4.2)\nrest(600)\n")
    _, edits = operation(doc, _compact("hold(1)\n")["body"][0])
    assert edits[0]["kind"] == "structural"


def test_an_edited_document_still_unparses():
    """The point of editing: the result is runnable code, not just valid JSON."""
    from awl.compact import decode

    doc = _compact("charge(4.2)\n")
    new_doc, _ = add_step(doc, into=["body"], node=_compact("rest(600)\n")["body"][0])
    assert ast.unparse(ast.fix_missing_locations(decode(new_doc))) == "charge(4.2)\nrest(600)"


def test_an_edit_that_violates_the_domain_is_rejected():
    """The restriction objective, made operational."""
    with pytest.raises(jsonschema.ValidationError):
        validate_domain({"_type": "Call", "callee": "os.system"}, DOMAIN)


def test_a_forbidden_construct_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        validate_domain({"_type": "ClassDef"}, DOMAIN)


def test_a_permitted_callee_passes():
    validate_domain({"_type": "Call", "callee": "battery.device.charge"}, DOMAIN)


def test_a_generic_validator_enforces_the_same_rule():
    """The argument against a vendor keyword, asserted rather than stated.

    With a keyword such as x-awl-callees only aware code would know the rule,
    and a generic validator would have to ignore it and pass os.system. That
    inverts the restriction into a hint.
    """
    validator = jsonschema.validators.validator_for(DOMAIN)(DOMAIN)
    assert not validator.is_valid({"_type": "Call", "callee": "os.system"})
    assert validator.is_valid({"_type": "Call", "callee": "battery.device.rest"})
