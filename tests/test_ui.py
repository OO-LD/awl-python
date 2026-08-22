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


def test_a_level_renders_a_block_for_each_level_below_it():
    """Standing on a module, `procedure` has to be visible and openable.

    A declaration does not run, so it is not a step and never appeared on the
    canvas that draws what runs. That made the module a dead end with the only
    way in sitting in a list beside the canvas.
    """
    model = _nested()
    module = model.flow("")
    assert [entry["name"] for entry in module["sublevels"]] == ["procedure"]
    assert module["sublevels"][0]["steps"] == 5, "and says how much is inside it"
    assert len(module["sublevels"][0]["span"]) == 4, "so a canvas can locate the block"


def test_a_sublevel_block_is_not_a_step():
    """It stands for a level. Nothing flows through it, so it has no place in
    the next chain and would be a lie in the plan.
    """
    model = _nested()
    module = model.flow("")
    assert not [step for step in module["steps"] if step["parser_type_name"] == "FunctionDef"]


def test_the_source_can_be_edited_back():
    """Both ways, or the source pane is a read-only echo."""
    model = _nested()
    answer = model.set_source(NESTED.replace("rest(600)", "rest(900)\n        settle()"))
    assert answer["ok"]
    assert [step.get("callee") for step in model.flow("procedure")["steps"]] == [
        None,
        None,
        "charge",
        "rest",
        "settle",
        None,
    ]


def test_source_that_does_not_parse_changes_nothing():
    """A half-typed edit is the normal state of a source pane, and a canvas
    rebuilt from a partial tree would flicker through files that never existed.
    """
    model = _nested()
    before = model.source
    answer = model.set_source("def procedure(:\n")
    assert not answer["ok"]
    assert answer["line"] == 1
    assert model.source == before
    assert model.flow("procedure")["steps"], "the canvas still has something to draw"


def _device(charge):
    """A stand-in for the hardware module the procedure imports.

    A namespace rather than a ModuleType: `from battery.device import charge`
    is an attribute lookup on whatever sits in sys.modules, so this is enough,
    and it is enough for a type checker too.
    """
    import types

    return types.SimpleNamespace(charge=charge, rest=lambda seconds: None)


def test_running_the_procedure_says_what_ran():
    """A real run, traced, joined to the plan by span."""
    model = _nested()
    calls: list[float] = []
    result = model.run("procedure", 3, modules={"battery.device": _device(calls.append)})
    assert result["ok"]
    assert calls == [4.2, 4.2, 4.2], "it really ran, three times"
    executed = [record for record in result["overlay"]["executions"] if record["executed"]]
    assert len(executed) == len(model.flow("procedure")["steps"])


def test_a_run_that_raises_still_says_how_far_it_got():
    """A step that raised is a fact about the procedure, not a lost run."""
    model = _nested()

    def explode(volts: float) -> None:
        raise RuntimeError("supply tripped")

    result = model.run("procedure", 3, modules={"battery.device": _device(explode)})
    assert not result["ok"]
    assert "supply tripped" in result["error"]
    assert any(record["executed"] for record in result["overlay"]["executions"])


def test_the_sample_runs_and_says_how_often_and_which_way():
    """The overlay is only worth drawing if it carries more than "it ran".

    The tracer reads the file to work out which loop a frame is in and which
    way a branch went, so a `file` label that is not on disk silently costs
    every iteration count and every branch outcome. The steps still report as
    executed, which is what made it easy to miss.
    """
    model = ui.open_sample()
    result = model.run("procedure", 3)
    assert result["ok"]

    executions = result["overlay"]["executions"]
    charge = next(record for record in executions if record.get("callee") == "charge")
    assert charge["iterations"] == [0, 1, 2], "the loop ran three times, and says so"

    branch = next(record for record in executions if record.get("branch_taken"))
    assert branch["branch_taken"] == [False, True], "and the branch went both ways"


def test_a_structural_edit_is_recorded_rather_than_refused():
    """add_step, delete_step and reorder carry no span, and reading one raised.

    A structural patch names a path and an operation, because moving a
    statement is not a range of characters. Every structural operation was
    unreachable through this class until the patch tier was read before the
    span.
    """
    model = ui.open_sample()
    before = len(model.flow("procedure")["steps"])
    added = {"@type": "Call", "func": {"var": "rest"}, "args": [{"literal": 30}]}
    model.apply("add_step", into=["body", 7, "body"], node=added)

    assert [edit.get("kind") for edit in model.edits] == ["structural"]
    assert model.set_source(model.regenerate())["ok"]
    assert len(model.flow("procedure")["steps"]) == before + 1


def test_a_structural_edit_regenerates_and_says_so_in_advance():
    """Adding a statement is not a range of characters.

    Nothing routes a structural patch through a concrete-syntax rewrite, so
    the whole module is regenerated and its comments do not survive. That loss
    is accepted for now rather than hidden: `reformats()` says the next call
    will take that path, so a canvas can warn before it happens rather than a
    reader finding it in a diff.
    """
    model = ui.open_sample()
    assert not model.reformats()

    model.apply("delete_step", path=["body", 7, "body", 4])
    assert model.reformats(), "and it says so before it is asked"

    produced = model.to_source()
    assert produced, "which is the code, not a refusal"
    assert "Charge and rest" in produced, "the docstring survives; a comment would not"


def test_a_resolved_class_is_not_the_same_as_an_unread_call():
    """`opens` returns None for two different reasons, and a canvas that has
    only that answer labels a constructor "source not read".

    `Report` resolved perfectly well. It is a class, and a class is not a
    level.
    """
    model = ui.open_sample()
    steps = model.flow("procedure")["steps"]

    constructor = next(step for step in steps if step.get("callee") == "Report")
    assert model.opens(constructor) is None, "a class is not a level"
    resolved = model.refers(constructor)
    assert resolved is not None and resolved["symbol"] == "Report", "but it did resolve"

    call = next(step for step in steps if step.get("callee") == "charge")
    assert model.opens(call) == ("awl.ui.sample", "charge")
    named = model.refers(call)
    assert named is not None and named["symbol"] == "charge"


def test_a_step_identity_does_not_survive_an_edit_elsewhere():
    """A known limitation, pinned so it cannot change quietly.

    Step identities are positional counters, so inserting a line anywhere
    earlier renumbers everything after it. Editing `settle` renames ten of the
    eleven steps in `procedure`, and `step#12` stops being an `Assign` and
    becomes an `Expr`.

    That is sound within one snapshot, which is all the plan minted them for,
    and not enough for an editor: a selection, a trace overlay or any stored
    annotation keyed on a step IRI is wrong after any edit. Two graphs of the
    same file taken either side of an edit cannot be joined even where the
    statements are untouched.
    """
    model = ui.open_sample()
    before = {step["id"]: step["parser_type_name"] for step in model.flow("procedure")["steps"]}

    model.set_source(
        model.source.replace(
            '    """Let the cell relax. The bottom of the stack, and deliberately empty."""',
            '    """Let the cell relax."""\n    return None',
        )
    )
    after = {step["id"]: step["parser_type_name"] for step in model.flow("procedure")["steps"]}

    kept = [identity for identity in before if after.get(identity) == before[identity]]
    assert len(kept) < len(before), "positional identity does not survive an insertion earlier in the file"


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
