"""M11: runtime tracing, attributed to AST nodes by span.

Imports only the module under test and the contracts package.
"""

import sys
from pathlib import Path

from awl.trace import trace


def test_events_carry_expression_level_positions():
    """Not line-level. Each operand of `a + 2` is separately attributable.

    Filter by filename: the tracer also sees its own caller's frame, so an
    unfiltered assertion could pass on a coincidental column match. Verified
    distinct spans for `<demo>`: (4,5) `a`, (8,9) `2`, (4,9) `a + 2`, (0,1) the
    target `b`. Some repeat across opcodes; assert membership, not the exact
    sequence, which varies by interpreter version.
    """
    events = trace(lambda: exec(compile("b = a + 2", "<demo>", "exec"), {"a": 1}))  # noqa: S102
    spans = [
        (event["span"]["startCol"], event["span"]["endCol"])
        for event in events
        if event["kind"] == "line" and event["span"]["file"] == "<demo>"
    ]
    assert (4, 5) in spans, "the operand `a`"
    assert (8, 9) in spans, "the operand `2`"
    assert (4, 9) in spans, "the BinOp `a + 2`"


def test_no_position_packing_survives_anywhere():
    """Correction 1: co_positions() replaced `lineno * 1000 + col_offset`.

    The packing works only on code the tracer compiled itself, which is why
    library internals were invisible to it. It also came with a decode bug that
    made col_offset always equal lineno.
    """
    import awl.trace

    source = Path(awl.trace.__file__).read_text(encoding="utf-8")
    assert "1000" not in source


def test_c_callees_are_named():
    """settrace cannot see these; setprofile can, and gives the FQN M2 mints."""
    import math

    events = trace(lambda: math.sqrt(2))
    assert "math.sqrt" in [event["callee"] for event in events if event["kind"] == "c_call"]


def test_a_c_call_follows_the_span_of_its_call_site():
    """Both hooks run at once, so the interleaving carries the position.

    setprofile gives the callee no position of its own, so this ordering is
    the only thing that attributes a C call to a line of source.
    """
    import math

    def work():
        return math.sqrt(2)

    events = trace(work)
    index = next(i for i, event in enumerate(events) if event.get("callee") == "math.sqrt")
    preceding = [event for event in events[:index] if "span" in event]
    assert preceding, "a positioned event precedes the C call"
    assert preceding[-1]["span"]["file"] == __file__


def test_records_which_branch_was_taken():
    """The claim with no precedent. A repeated line number is not evidence."""

    def work(flag):
        if flag:
            return "then"
        return "else"

    taken = [event for event in trace(lambda: work(True)) if event["kind"] == "branch"]
    assert taken, "a branch event is emitted"
    assert taken[0]["taken"] is True

    not_taken = [event for event in trace(lambda: work(False)) if event["kind"] == "branch"]
    assert not_taken[0]["taken"] is False
    assert taken[0]["span"] == not_taken[0]["span"], "same branch, different outcome"


def test_a_branch_event_points_at_the_if_statement():
    """The span is the join key to the node the editor renders."""

    def work(flag):
        if flag:
            return "then"
        return "else"

    event = next(e for e in trace(lambda: work(True)) if e["kind"] == "branch")
    assert event["span"]["file"] == __file__
    line = event["span"]["startLine"]
    source = Path(__file__).read_text(encoding="utf-8").splitlines()[line - 1]
    assert source.strip() == "if flag:"


def test_records_the_iteration_ordinal():
    """PROV has no loop counter, so the ordinal is carried on the event.

    Without it, two passes through a loop differ only by list position, which
    is the defect this module exists to fix.
    """

    def work():
        total = 0
        for i in range(3):
            total += i
        return total

    ordinals = sorted({event["iteration"] for event in trace(work) if event.get("iteration") is not None})
    assert ordinals == [0, 1, 2], ordinals


def test_a_while_loop_also_counts_iterations():
    """The construct the running example uses."""

    def work():
        i = 0
        while i < 2:
            i += 1
        return i

    ordinals = sorted({event["iteration"] for event in trace(work) if event.get("iteration") is not None})
    assert ordinals == [0, 1], ordinals


def test_a_nested_loop_reports_the_innermost_ordinal():
    """Otherwise the outer loop would mask the inner one's count."""

    def work():
        seen = 0
        for _outer in range(2):
            for _inner in range(3):
                seen += 1
        return seen

    ordinals = sorted({event["iteration"] for event in trace(work) if event.get("iteration") is not None})
    assert ordinals == [0, 1, 2], ordinals


def test_ordinals_restart_for_a_second_call():
    """Counters are per frame, not per run.

    Keeping one running total would report 0..5 for a three-pass loop called
    twice, which reads as a six-iteration loop that never existed.
    """

    def work():
        for _i in range(3):
            pass

    def twice():
        work()
        work()

    ordinals = sorted({event["iteration"] for event in trace(twice) if event.get("iteration") is not None})
    assert ordinals == [0, 1, 2], ordinals


def test_index_is_a_total_order():
    events = trace(lambda: sum([1, 2]))
    assert len(events) == len({event["index"] for event in events})
    assert [event["index"] for event in events] == list(range(len(events)))


def test_the_previous_hooks_are_restored():
    """Clearing them would silently disable the surrounding coverage run.

    This test suite runs under pytest-cov, so the assertion is not theoretical.
    """
    before_trace, before_profile = sys.gettrace(), sys.getprofile()
    trace(lambda: sum([1, 2]))
    assert sys.gettrace() is before_trace
    assert sys.getprofile() is before_profile


def test_source_without_a_readable_file_still_yields_spans():
    """An exec'd string has no file, so branch and iteration are unavailable.

    Degrading to spans-only is the right failure: the alternative is inventing
    arms that cannot be located.
    """
    events = trace(lambda: exec(compile("x = 1", "<demo>", "exec"), {}))  # noqa: S102
    assert [event for event in events if event.get("span", {}).get("file") == "<demo>"]
    assert not [event for event in events if event["kind"] == "branch" and event["span"]["file"] == "<demo>"]


def test_every_event_matches_the_contract():
    from awl import contracts

    def work():
        if True:
            for _i in range(2):
                sum([1, 2])

    events = trace(work)
    assert events
    for event in events:
        contracts.validate(event, "trace-event")


def test_the_span_algebra_is_exercised_outside_the_callback():
    """CPython does not trace the trace function, so everything reached from
    inside it is invisible to coverage. These are the same helpers the tracer
    uses to decide `taken` and `iteration`, checked where measurement works.
    """
    from awl.trace import _contains, _within

    body = (10, 4, 12, 20)
    assert _contains(body, (10, 4)), "inclusive at the start"
    assert _contains(body, (12, 20)), "inclusive at the end"
    assert _contains(body, (11, 0)), "a line in the middle, any column"
    assert not _contains(body, (10, 3)), "one column before"
    assert not _contains(body, (12, 21)), "one column after"
    assert not _contains(None, (10, 4)), "an absent arm contains nothing"

    assert _within((11, 8, 11, 20), body)
    assert not _within(body, body), "strict: a body is not nested in itself"
    assert not _within(body, (11, 0, 11, 9)), "an outer range is not nested"
    assert not _within(None, body)


def test_structures_are_read_from_the_file_and_cached():
    """The branch arms come from the source, so a file-less code object gets
    nothing rather than a guess.
    """
    from awl.trace import _structures

    found = _structures(__file__)
    assert found, "this test file contains if and for statements"
    assert {structure.kind for structure in found} == {"branch", "loop"}
    assert _structures(__file__) is found, "cached; parsing per event would be quadratic"
    assert _structures("<demo>") == ()
    assert _structures("no/such/file.py") == ()


def test_a_while_registers_as_both_a_branch_and_a_loop():
    """Its test decides an arm and its body repeats, so it is both."""
    import tempfile
    from pathlib import Path

    from awl.trace import _structures

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.py"
        path.write_text("i = 0\nwhile i < 2:\n    i += 1\n", encoding="utf-8")
        kinds = [structure.kind for structure in _structures(str(path))]
    assert sorted(kinds) == ["branch", "loop"]
