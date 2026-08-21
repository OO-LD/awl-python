"""Runtime tracing: what ran, along which branch, for how many iterations.

Uses ``sys.settrace`` with opcode tracing for expression-level position, plus
an interleaved ``sys.setprofile`` to name C callees the static analysis cannot
see. Both hooks are independent slots and can be active at once, which is what
lets a C call be attributed to a source position.

Only one trace function and one profile function exist per thread, so this
conflicts with debuggers, ``coverage`` and profilers. The previous hooks are
saved and restored rather than cleared, so a surrounding coverage run survives,
but the two cannot observe the same code at the same time.

One consequence to read correctly: CPython does not trace the trace function
itself, so every line reached from inside the callback is invisible to any
coverage tool, and this module reports a low percentage no matter how well it
is tested. The span algebra is therefore also exercised directly, outside the
callback, where measurement works.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from functools import lru_cache
from types import CodeType, FrameType
from typing import Any

__all__ = ["trace"]

_Point = tuple[int, int]
_Range = tuple[int, int, int, int]

_positions_cache: dict[CodeType, list[Any]] = {}


def _positions(code: CodeType) -> list[Any]:
    """Return and memoize ``co_positions()`` for *code*.

    Recomputing per event would make the tracer quadratic in program length,
    since it fires once per instruction.
    """
    cached = _positions_cache.get(code)
    if cached is None:
        cached = list(code.co_positions())
        _positions_cache[code] = cached
    return cached


def _position(frame: FrameType) -> dict[str, Any] | None:
    """Return the source span of the instruction currently executing.

    Uses ``co_positions()`` (PEP 657, Python 3.11+) rather than packing the
    column into ``f_lineno``, so this works on code the tracer did not compile.
    The packing trick only ever saw code the tracer compiled itself, which is
    why library internals were invisible to it.
    """
    index = frame.f_lasti // 2
    positions = _positions(frame.f_code)
    if index >= len(positions):
        return None
    line, end_line, col, end_col = positions[index]
    if line is None:
        return None
    return {
        "file": frame.f_code.co_filename,
        "start_line": line,
        "start_col": col or 0,
        "end_line": end_line or line,
        "end_col": end_col or 0,
    }


def _envelope(nodes: list[ast.stmt]) -> _Range | None:
    """Return the span covering every statement in *nodes*."""
    if not nodes:
        return None
    first, last = nodes[0], nodes[-1]
    if last.end_lineno is None or last.end_col_offset is None:
        return None
    return (first.lineno, first.col_offset, last.end_lineno, last.end_col_offset)


def _node_range(node: ast.stmt | ast.expr) -> _Range | None:
    """Return the span of a single node, or None if it carries no end position."""
    if node.end_lineno is None or node.end_col_offset is None:
        return None
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _contains(area: _Range | None, point: _Point) -> bool:
    """Return whether *point* falls inside *area*, comparing (line, col) pairs."""
    if area is None:
        return False
    start_line, start_col, end_line, end_col = area
    return (start_line, start_col) <= point <= (end_line, end_col)


class _Structure:
    """One control structure, reduced to the spans the tracer compares against.

    Attributes
    ----------
    kind : str
        ``"branch"`` for ``if``, ``"loop"`` for ``for`` and ``while``. A
        ``while`` is both, and is registered twice.
    file : str
        The source file, carried so a branch event can report its own span.
    span : tuple
        The whole statement, reported on the event so two runs of the same
        branch are recognisably the same branch.
    test : tuple or None
        The condition, whose execution opens a pending branch decision.
    body, orelse : tuple or None
        Where control lands, which is how the decision is resolved.
    nested : tuple of int
        Indices of the loops lying inside this one's body, whose ordinals reset
        when this one advances.
    """

    __slots__ = ("body", "file", "kind", "nested", "orelse", "span", "test")

    def __init__(self, kind, file, span, test, body, orelse):
        self.kind = kind
        self.file = file
        self.span = span
        self.test = test
        self.body = body
        self.orelse = orelse
        self.nested: tuple[int, ...] = ()


@lru_cache(maxsize=64)
def _structures(filename: str) -> tuple[_Structure, ...]:
    """Return the control structures declared in *filename*.

    Returns an empty tuple when the file cannot be read or parsed, which is the
    case for ``exec``'d strings and for interactive input. Spans still work
    there; only branch and iteration reporting is unavailable, because there is
    no source to locate the arms in.
    """
    try:
        with open(filename, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=filename)
    except (OSError, SyntaxError, ValueError):
        return ()

    found: list[_Structure] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If | ast.While | ast.For | ast.AsyncFor):
            continue
        span = _node_range(node)
        if span is None:
            continue
        if isinstance(node, ast.If):
            found.append(
                _Structure(
                    "branch",
                    filename,
                    span,
                    _node_range(node.test),
                    _envelope(node.body),
                    _envelope(node.orelse),
                )
            )
        elif isinstance(node, ast.While):
            body = _envelope(node.body)
            found.append(_Structure("branch", filename, span, _node_range(node.test), body, _envelope(node.orelse)))
            found.append(_Structure("loop", filename, span, None, body, None))
        else:
            found.append(_Structure("loop", filename, span, None, _envelope(node.body), None))

    # An inner loop's ordinal restarts on every pass of its enclosing loop.
    # Without this a 2x3 nest reports 0..5, which reads as a six-iteration loop
    # that never existed.
    for outer_index, outer in enumerate(found):
        if outer.kind != "loop":
            continue
        outer.nested = tuple(
            inner_index
            for inner_index, inner in enumerate(found)
            if inner.kind == "loop" and inner_index != outer_index and _within(inner.body, outer.body)
        )
    return tuple(found)


def _within(inner: _Range | None, outer: _Range | None) -> bool:
    """Return whether *inner* lies strictly inside *outer*."""
    if inner is None or outer is None or inner == outer:
        return False
    return _contains(outer, (inner[0], inner[1])) and _contains(outer, (inner[2], inner[3]))


class _Recorder:
    """Accumulates events and the per-frame state the orderings need.

    Loop counters and the pending branch decision are held per frame, keyed by
    the frame's identity and dropped when it returns, so recursion and repeated
    calls each get their own ordinals instead of one running total.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._frames: dict[int, dict[str, Any]] = {}

    def emit(self, **fields: Any) -> None:
        self.events.append({**fields, "index": len(self.events)})

    def enter_frame(self, frame: FrameType) -> None:
        self._frames[id(frame)] = {"iterations": {}, "inside": set(), "pending": None}

    def leave_frame(self, frame: FrameType) -> None:
        self._frames.pop(id(frame), None)

    def observe(self, frame: FrameType, span: dict[str, Any]) -> int | None:
        """Update loop and branch state for one positioned event.

        Returns
        -------
        int or None
            The ordinal of the innermost loop whose body contains the event.
        """
        state = self._frames.get(id(frame))
        if state is None:
            return None
        structures = _structures(span["file"])
        if not structures:
            return None
        point = (span["start_line"], span["start_col"])
        self._resolve_branch(state, structures, point)
        return self._update_loops(state, structures, point)

    def _resolve_branch(self, state, structures, point: _Point) -> None:
        pending = state["pending"]
        if pending is not None and not _contains(pending.test, point):
            state["pending"] = None
            self.emit(
                kind="branch",
                span={
                    "file": pending.file,
                    "start_line": pending.span[0],
                    "start_col": pending.span[1],
                    "end_line": pending.span[2],
                    "end_col": pending.span[3],
                },
                taken=_contains(pending.body, point),
            )
        if state["pending"] is None:
            for structure in structures:
                if structure.kind == "branch" and _contains(structure.test, point):
                    state["pending"] = structure
                    break

    def _update_loops(self, state, structures, point: _Point) -> int | None:
        ordinal = None
        for position, structure in enumerate(structures):
            if structure.kind != "loop":
                continue
            inside = _contains(structure.body, point)
            was_inside = position in state["inside"]
            if inside and not was_inside:
                state["iterations"][position] = state["iterations"].get(position, -1) + 1
                state["inside"].add(position)
                for nested in structure.nested:
                    state["iterations"].pop(nested, None)
                    state["inside"].discard(nested)
            elif not inside and was_inside:
                state["inside"].discard(position)
            if inside:
                ordinal = state["iterations"][position]
        return ordinal


def trace(fn: Callable[[], Any], *, capture_c_calls: bool = True) -> list[dict[str, Any]]:
    """Run *fn* under instrumentation and return the events it produced.

    Parameters
    ----------
    fn : callable
        Invoked with no arguments.
    capture_c_calls : bool, optional
        Also install a profile hook, so C callees are named. ``settrace`` alone
        cannot see them, and ``arg.__module__ + arg.__qualname__`` is exactly
        the identity awl.ids mints.

    Returns
    -------
    list of dict
        Each conforms to ``trace-event.schema.json``. ``index`` is a total
        order, so event sequence never depends on list position alone.

    Notes
    -----
    Overhead is large: ``f_trace_opcodes`` fires once per instruction. This is
    the mechanism for inspecting a run, not for production. ``sys.monitoring``
    with only ``BRANCH`` and ``CALL`` enabled is the cheap alternative, at the
    cost of the frame object and therefore of locals.

    Threads need ``threading.settrace`` separately; that is not handled here.
    """
    recorder = _Recorder()

    def tracer(frame: FrameType, event: str, arg: Any = None):
        frame.f_trace_opcodes = True
        if event == "call":
            recorder.enter_frame(frame)
        span = _position(frame)
        if span is not None:
            iteration = recorder.observe(frame, span)
            recorder.emit(
                kind="line" if event == "opcode" else event,
                span=span,
                iteration=iteration,
            )
        if event == "return":
            recorder.leave_frame(frame)
        return tracer

    def profiler(frame: FrameType, event: str, arg: Any) -> None:
        if event in ("c_call", "c_return"):
            module = getattr(arg, "__module__", "") or ""
            qualname = getattr(arg, "__qualname__", repr(arg))
            recorder.emit(kind=event, callee=f"{module}.{qualname}".lstrip("."))

    # Saved and restored rather than cleared: clearing would silently disable a
    # surrounding coverage run for the rest of the process.
    previous_trace = sys.gettrace()
    previous_profile = sys.getprofile()
    sys.settrace(tracer)
    if capture_c_calls:
        sys.setprofile(profiler)
    try:
        fn()
    finally:
        sys.setprofile(previous_profile)
        sys.settrace(previous_trace)
    return recorder.events
