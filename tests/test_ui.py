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


def test_two_fields_of_one_constructor_can_both_be_set():
    """Both patches replace the same call, so appending them overlapped.

    A collapsed node is written back by rebuilding the whole call, and the
    rebuilt node already holds every earlier change to it. Setting a voltage
    and then a rate raised on overlapping edits instead of writing both.
    """
    model = _model()
    model.set_value([*CONSTRUCTOR, "target_voltage"], 4.35)
    model.set_value([*CONSTRUCTOR, "c_rate"], 0.5)

    after = model.to_source()
    assert "target_voltage=4.35" in after
    assert "c_rate=0.5" in after
    assert len(model.edits) == 1, "one call, one patch"


def test_a_literal_can_be_edited_more_than_once():
    """The first edit used to delete what the next one would point at.

    Replacing a literal wrote a bare node with no span, so it vanished from a
    canvas drawn from spans and could never be selected again. The same family
    as the constructor overlap: an edit that destroys its own address.
    """
    model = _model()
    model.set_value(LITERAL, 900)
    assert "span" in ui._descend(model.document, LITERAL), "still locatable"

    model.set_value(LITERAL, 1200)
    assert "rest(1200)" in model.to_source()


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


NESTED = """from battery.device import charge, rest


def procedure(cycles):
    i = 0
    while i < cycles:
        charge(4.2)
        rest(600)
        i += 1
"""
DEVICE = "def charge(volts):\n    apply_voltage(volts)\n    settle()\n\n\ndef rest(seconds):\n    wait(seconds)\n"


def _nested():
    return ui.load(NESTED, module="battery.procedure", file="procedure.py", index={"battery.device": DEVICE})


def test_a_module_says_which_levels_it_offers():
    """Where a canvas starts.

    Both canvases built against this opened at module scope and found a
    docstring and two imports with nothing to descend into: a module is
    declarations, and the flow worth drawing is inside a function. A `def` is
    deliberately not a step, so which levels exist is asked here rather than
    by making declarations part of what runs.
    """
    model = _nested()
    assert model.scopes() == [{"scope": "", "steps": 1}, {"scope": "procedure", "steps": 5}]


def test_a_level_is_a_scope():
    """What a canvas draws: the steps of one scope and the edges between them.

    Two calls in sequence are `a -> b`; a loop is a step of its own between
    them, with edges out of it.
    """
    model = _nested()
    level = model.flow("procedure")
    kinds = [step["parser_type_name"] for step in level["steps"]]
    assert kinds == ["Assign", "While", "Expr", "Expr", "AugAssign"]
    assert {edge["kind"] for edge in level["edges"]} >= {"next", "when_true", "repeat"}


def test_the_module_scope_is_a_level_like_any_other():
    assert [step["parser_type_name"] for step in _nested().flow()["steps"]] == ["ImportFrom"]


def test_a_call_opens_into_the_function_it_names():
    model = _nested()
    charge = next(step for step in model.flow("procedure")["steps"] if step.get("callee") == "charge")
    assert model.opens(charge) == ("battery.device", "charge")


def test_descending_is_the_same_thing_again():
    """Unlimited, because nothing counts depth: a scope is a name, and
    descending produces another scope.
    """
    model = _nested()
    charge = next(step for step in model.flow("procedure")["steps"] if step.get("callee") == "charge")
    inner = model.descend(charge)
    assert isinstance(inner, ui.EditorModel)
    assert [step.get("callee") for step in inner.flow("charge")["steps"]] == ["apply_voltage", "settle"]


def test_a_call_whose_source_was_never_read_does_not_open():
    """Drawing it as a leaf would say it has no body, which is a different
    claim from not having been read.
    """
    model = _nested()
    inner = model.descend(next(s for s in model.flow("procedure")["steps"] if s.get("callee") == "charge"))
    apply_voltage = next(step for step in inner.flow("charge")["steps"] if step.get("callee") == "apply_voltage")
    assert inner.opens(apply_voltage) is None
    assert inner.descend(apply_voltage) is None


def test_a_step_that_calls_nothing_does_not_open():
    model = _nested()
    assign = next(step for step in model.flow("procedure")["steps"] if step["parser_type_name"] == "Assign")
    assert model.opens(assign) is None


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
