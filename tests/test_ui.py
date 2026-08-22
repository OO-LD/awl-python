"""The model every editor variant sits on.

Imports only the module under test and the contracts package. There is no
browser here on purpose: what a canvas does with a document is the variant's
business, and what an edit means is not.
"""

import pytest

from awl import contracts, ui

ROOT = contracts.CORPUS_DIR / "tier2_dataclass"
CONSTRUCTOR = ["body", 3, "body", 1, "body", 0, "args", 0]
LITERAL = ["body", 3, "body", 1, "body", 1, "args", 0]


def _model():
    return ui.load(
        (ROOT / "procedure.py").read_text(encoding="utf-8"),
        module="tier2_dataclass.procedure",
        file="procedure.py",
        index={"tier2_dataclass.params": (ROOT / "params.py").read_text(encoding="utf-8")},
    )


def test_the_document_a_canvas_draws_is_located():
    """Every node carries a span, including the collapsed constructor.

    The collapse builds that node itself, so with spans threaded only into the
    encoder it was the one node in a located document with no position: an
    editor could show a voltage and had nowhere to write a change back to.
    """
    model = _model()
    node = ui._descend(model.document, CONSTRUCTOR)
    assert node["@type"] == ["ChargeParam"]
    assert len(node["span"]) == 4


def test_editing_a_collapsed_field_touches_only_that_call():
    """The property write-back exists for.

    A collapsed node stands for a whole call and its fields are bare values,
    so there is nothing to point a patch at. Rebuilding the call and replacing
    it reformats the call and nothing else.
    """
    model = _model()
    model.set_value([*CONSTRUCTOR, "target_voltage"], 4.35)

    before = model.source.splitlines()
    after = model.to_source().splitlines()
    changed = [n for n, (was, now) in enumerate(zip(before, after, strict=True)) if was != now]
    assert len(changed) == 1
    assert "target_voltage=4.35" in after[changed[0]]
    assert "c_rate=0.23" in after[changed[0]], "the untouched field is not lost"


def test_editing_a_literal_touches_only_the_literal():
    model = _model()
    model.set_value(LITERAL, 900)
    after = model.to_source()
    assert "rest(900)" in after
    assert after.splitlines()[0] == model.source.splitlines()[0], "the docstring is untouched"


def test_two_edits_compose_without_reflowing_the_file():
    """Patches are applied right to left, so earlier offsets stay valid."""
    model = _model()
    model.set_value([*CONSTRUCTOR, "target_voltage"], 4.35)
    model.set_value(LITERAL, 900)

    before = model.source.splitlines()
    after = model.to_source().splitlines()
    assert sum(1 for was, now in zip(before, after, strict=True) if was != now) == 2
    assert len(before) == len(after)


def test_an_edit_that_cannot_be_located_is_refused():
    """Rather than rewriting the file to make the change fit."""
    model = _model()
    with pytest.raises(LookupError, match="span"):
        model.set_value(["body", 3, "name"], "renamed")


def test_an_unknown_operation_is_refused():
    model = _model()
    with pytest.raises(ValueError, match="unknown operation"):
        model.apply("rewrite_everything")


def test_the_document_still_regenerates_its_source():
    """The editor model is the compact document, so this must keep holding."""
    import ast

    model = _model()
    assert model.regenerate() == ast.unparse(ast.parse(model.source))


def test_every_variant_pairs_a_canvas_with_a_form():
    """Three variants, and the comparison is only worth anything if what
    differs between them is the paradigm rather than the plumbing.
    """
    assert set(ui.VARIANTS) == {"blockly", "reactflow", "reactflow_jedison"}
    canvases = {canvas for canvas, _form, _note in ui.VARIANTS.values()}
    forms = {form for _canvas, form, _note in ui.VARIANTS.values()}
    assert len(canvases) == 2 and len(forms) == 2, "each axis is varied, not both at once"


def test_the_operations_are_the_editors_and_not_reimplemented():
    """A variant that grew its own edit semantics would measure those."""
    from awl import editor

    assert set(ui.OPERATIONS) <= set(editor.__all__)
