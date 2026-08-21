"""Joining a recorded run onto the plan.

Imports only the module under test, the control-flow graph it consumes, the
tracer that produces its other input, and the contracts package.
"""

import importlib.util
import sys
import textwrap

import pytest

from awl.controlflow import analyze
from awl.execution import join
from awl.trace import trace

SOURCE = textwrap.dedent("""
    def charge(v):
        return v


    def rest(s):
        return s


    def procedure(cycles):
        i = 0
        while i < cycles:
            if i == 0:
                charge(4.2)
            rest(600)
            i += 1
        return i
""").lstrip()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Trace a real run of the procedure and join it onto its plan."""
    path = tmp_path_factory.mktemp("execution") / "procedure.py"
    path.write_text(SOURCE, encoding="utf-8")

    spec = importlib.util.spec_from_file_location("_awl_execution_sample", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    events = trace(lambda: module.procedure(3))
    plan = analyze(SOURCE, module="procedure", file=str(path))
    joined = join(plan, events)
    return {
        (entry["callee"] or entry["condition"]): entry
        for entry in joined["executions"]
        if entry["callee"] or entry["condition"]
    }


def test_a_step_inside_a_guard_only_ran_on_the_iterations_that_passed_it(run):
    """The fact with no precedent: which arm ran, on which pass.

    `charge` sits behind `if i == 0` inside the loop, so it ran on iteration 0
    and on no other. `rest` sits outside the guard and ran on all three.
    """
    assert run["charge"]["iterations"] == [0]
    assert run["rest"]["iterations"] == [0, 1, 2]


def test_the_loop_iteration_count_is_recorded(run):
    """PROV has no loop counter, so the ordinal is carried on the event."""
    assert run["rest"]["iterationCount"] == 3


def test_both_outcomes_of_a_branch_are_recorded(run):
    """`i == 0` was true once and false twice, and both are facts about the run."""
    assert run["i == 0"]["branchTaken"] == [False, True]


def test_every_matched_step_is_marked_executed(run):
    for label in ("charge", "rest", "i == 0", "i < cycles"):
        assert run[label]["executed"] is True, label


def test_the_event_count_does_not_claim_to_be_an_execution_count(run):
    """Opcode tracing fires many times per statement.

    Reporting that as "ran 5 times" would be a plain falsehood, so the count
    is named for what it is and the execution count comes from the ordinals.
    """
    assert run["charge"]["eventCount"] > 1
    assert run["charge"]["iterations"] == [0], "ran on exactly one pass"


def test_a_step_that_never_ran_is_reported_rather_than_omitted():
    """ "In the plan and absent from the run" is an answer; a missing node is not."""
    plan = analyze("def f(flag):\n    if flag:\n        a()\n    b()\n", file="p.py")
    joined = join(plan, [])
    assert joined["executions"], "steps are present"
    assert all(entry["executed"] is False for entry in joined["executions"])


def test_an_event_with_no_matching_step_is_ignored():
    """A trace covers the interpreter, not only the file under analysis."""
    plan = analyze("a()\n", file="p.py")
    joined = join(
        plan,
        [
            {
                "kind": "line",
                "index": 0,
                "span": {"file": "elsewhere.py", "startLine": 1, "startCol": 0, "endLine": 1, "endCol": 1},
            }
        ],
    )
    assert all(entry["executed"] is False for entry in joined["executions"])


def test_an_event_inside_a_statement_still_attributes_to_that_step():
    """The tracer reports expression-level positions, so an event lands inside
    a statement rather than on it. Without the line-level fallback almost
    nothing would match and a real run would look like it did nothing.
    """
    plan = analyze("charge(4.2)\n", file="p.py")
    joined = join(
        plan,
        [
            {
                "kind": "line",
                "index": 0,
                "span": {"file": "p.py", "startLine": 1, "startCol": 7, "endLine": 1, "endCol": 10},
            }
        ],
    )
    assert joined["executions"][0]["executed"] is True
