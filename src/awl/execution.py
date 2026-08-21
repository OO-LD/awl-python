"""Join a recorded run onto the plan: what actually ran, and how often.

The plan says a step *may* run, under a condition, possibly repeatedly. A trace
says what happened. Both are keyed by source span, so the join needs no extra
machinery and no instrumentation of the plan.

What this makes answerable, and what nothing in the surveyed prior art records:
which arm of a branch was taken on a given run, and how many times a loop body
actually executed. Static workflow languages omit branching, orchestrators
expand it away before recording, and systems with real control flow keep the
branch and iteration logic out of their provenance graphs.

A step that never ran is reported as such rather than omitted. "Present in the
plan and absent from the run" is an answer; a missing node is not.
"""

from __future__ import annotations

from typing import Any

__all__ = ["join"]


def _key(span: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """Return the span's join key, or None when it carries no position."""
    if not span:
        return None
    return (
        span.get("file"),
        span.get("start_line"),
        span.get("start_col"),
    )


def _line_key(span: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """Return a line-level key, used only when no exact span matched.

    An expression-level trace event sits inside its statement rather than on
    it, so an exact match finds the sub-expression and misses the step. Falling
    back to the line recovers the step without inventing a link, because a
    statement owns its line.
    """
    if not span:
        return None
    return (span.get("file"), span.get("start_line"))


def _index(steps):
    """Return the exact-span and line-level lookup tables for *steps*."""
    exact: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    by_line: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for step in steps:
        key = _key(step["span"])
        if key is not None:
            exact.setdefault(key, []).append(step)
        line = _line_key(step["span"])
        if line is not None:
            by_line.setdefault(line, []).append(step)
    return exact, by_line


def _finish(record: dict[str, Any]) -> dict[str, Any]:
    """Turn accumulated sets into the ordered output entry."""
    iterations = sorted(record.pop("iterations"))
    taken = sorted(record.pop("branch_taken"))
    entry = {**record, "iterations": iterations}
    if iterations:
        # One more than the highest ordinal: ordinals count from zero.
        entry["iteration_count"] = iterations[-1] + 1
    if taken:
        entry["branch_taken"] = taken
    return entry


def join(plan: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Attribute trace events to plan steps.

    Parameters
    ----------
    plan : dict
        A control-flow graph, as returned by ``awl.controlflow.analyze``.
    events : list of dict
        ``TraceEvent`` documents, as returned by ``awl.trace.trace``.

    Returns
    -------
    dict
        ``{"file": ..., "executions": [...]}``. One entry per step, carrying
        whether it ran, how many trace events were attributed to it, the loop
        ordinals it ran under, and for a branch the outcomes recorded. A step
        that never ran carries ``executed: false``.

        ``event_count`` is the number of attributed events, **not** the number
        of times the step executed: opcode tracing fires many times per
        statement. The honest execution count is ``iteration_count``, which is
        derived from the loop ordinals the tracer recorded.

    Notes
    -----
    Events are matched to steps by exact span first and by line second. The
    tracer reports expression-level positions, so an event usually falls
    *inside* a statement rather than on it; without the line-level fallback
    almost nothing would match, which would look like a run that did nothing.
    """
    exact, by_line = _index(plan["steps"])

    observed: dict[str, dict[str, Any]] = {
        step["id"]: {
            "step": step["id"],
            "callee": step.get("callee"),
            "condition": step.get("condition"),
            "span": step["span"],
            "executed": False,
            "event_count": 0,
            "iterations": set(),
            "branch_taken": set(),
        }
        for step in plan["steps"]
    }

    for event in events:
        span = event.get("span")
        matched = exact.get(_key(span) or ()) or by_line.get(_line_key(span) or ())
        if not matched:
            continue
        for step in matched:
            record = observed[step["id"]]
            record["executed"] = True
            record["event_count"] += 1
            if event.get("iteration") is not None:
                record["iterations"].add(event["iteration"])
            if event.get("kind") == "branch" and "taken" in event:
                record["branch_taken"].add(bool(event["taken"]))

    return {
        "file": plan["file"],
        "executions": [_finish(record) for record in observed.values()],
    }
