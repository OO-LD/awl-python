"""The control-flow graph: which steps are connected by execution logic.

An ordered statement list says a step comes second. It does not say a step runs
*only if* a condition held, or *repeatedly*, or *not at all* on some path. That
is what a plan is, and it is what an ordered body cannot express.

Edges are typed by the reason control moves, so a query asks "which steps run
when this test is true" rather than reconstructing it from nesting:

============  ===========================================================
``next``      unconditional sequence
``when_true``  the test held
``when_false`` the test did not hold, including falling past an ``if``
``each_item``  one pass of a ``for``
``exhausted`` the iterable ran out
``repeat``    the back edge closing a loop
============  ===========================================================

Joining with a trace answers the other half of the same profile's obligation,
what actually ran, because both sides are keyed by source span.
"""

from __future__ import annotations

import ast
from typing import Any

from awl.ids import mint
from awl.vocab import node_type_for

__all__ = ["EDGE_KINDS", "analyze", "as_document"]

_Exit = tuple[str, str]


def _span(node: ast.AST, file: str) -> dict[str, Any] | None:
    """Return the source span of *node*, or None when it carries no position."""
    lineno = getattr(node, "lineno", None)
    if lineno is None:
        return None
    return {
        "file": file,
        "start_line": lineno,
        "start_col": getattr(node, "col_offset", 0),
        "end_line": getattr(node, "end_lineno", None) or lineno,
        "end_col": getattr(node, "end_col_offset", None) or 0,
    }


def _dotted(node: ast.AST | None) -> str | None:
    """Return the dotted name a node denotes, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _callee_of(node: ast.stmt) -> str | None:
    """Return the name a statement calls, when it is a call.

    A workflow's steps are its calls, so this is what makes a step nameable
    rather than merely locatable.
    """
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return _dotted(node.value.func)
    if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Call):
        return _dotted(node.value.func)
    return None


def _test_of(node: ast.stmt) -> ast.expr | None:
    """Return the expression a conditional or loop tests."""
    test = getattr(node, "test", None)
    if test is not None:
        return test
    if isinstance(node, ast.For | ast.AsyncFor):
        return node.iter
    return None


def _condition_of(node: ast.stmt) -> str | None:
    """Return the test as written, for display only.

    Deliberately not a query surface. It is unparsed source text, so it is
    sensitive to spacing and dies the moment a variable is renamed. What a
    query wants is the structure, which reaches it two ways: the names the
    test reads, below, and the document's own subtree, joined by span.
    """
    test = _test_of(node)
    return ast.unparse(test) if test is not None else None


def _condition_reads(node: ast.stmt) -> list[str]:
    """Return the names a condition reads.

    The queryable half of a condition. "Which loops depend on `cycles`" is a
    question about this; "which loops are spelled `i < cycles`" is not a
    question anyone asks.
    """
    test = _test_of(node)
    if test is None:
        return []
    seen = []
    for child in ast.walk(test):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id not in seen:
            seen.append(child.id)
    return seen


class _Graph:
    """Accumulates steps and typed edges."""

    def __init__(self, module: str, file: str) -> None:
        self.module = module
        self.file = file
        self.steps: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._counter = 0

    def step(self, node: ast.stmt, scope: str) -> str:
        """Record a step and return its identity."""
        self._counter += 1
        identity = mint(
            scheme="py",
            module=self.module,
            symbol=f"{scope}.step" if scope else "step",
            disambiguator=str(self._counter),
        )["iri"]
        self.steps.append({
            "id": identity,
            "node_type": node_type_for(type(node).__name__),
            "parser_type_name": type(node).__name__,
            "scope": scope,
            "callee": _callee_of(node),
            "condition": _condition_of(node),
            "condition_reads": _condition_reads(node),
            "span": _span(node, self.file),
        })
        return identity

    def edge(self, source: str, target: str, kind: str) -> None:
        self.edges.append({"from": source, "to": target, "kind": kind})


class _Builder:
    """Builds the graph, threading the exits that await a successor."""

    def __init__(self, graph: _Graph) -> None:
        self.graph = graph
        self._loops: list[tuple[str, list[_Exit]]] = []

    def sequence(self, body: list[ast.stmt], scope: str) -> tuple[str | None, list[_Exit]]:
        """Walk a statement list.

        Returns
        -------
        tuple
            The entry step, and the exits awaiting whatever follows. An empty
            exit list means control cannot fall out of this block, which is
            what a ``return`` produces.
        """
        entry: str | None = None
        pending: list[_Exit] = []
        for statement in body:
            found = self.statement(statement, scope)
            if found is None:
                continue
            node_entry, node_exits = found
            if entry is None:
                entry = node_entry
            for source, kind in pending:
                self.graph.edge(source, node_entry, kind)
            pending = node_exits
        return entry, pending

    def statement(self, node: ast.stmt, scope: str) -> tuple[str, list[_Exit]] | None:
        handler = getattr(self, f"_on_{type(node).__name__}", None)
        if handler is not None:
            return handler(node, scope)
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        identity = self.graph.step(node, scope)
        return identity, [(identity, "next")]

    def _on_If(self, node: ast.If, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        body_entry, body_exits = self.sequence(node.body, scope)
        if body_entry is not None:
            self.graph.edge(identity, body_entry, "when_true")
        else:
            body_exits = [(identity, "when_true")]

        else_entry, else_exits = self.sequence(node.orelse, scope)
        if else_entry is not None:
            self.graph.edge(identity, else_entry, "when_false")
        else:
            # No else arm: control falls past the conditional, and that is
            # still a when_false edge. Emitting it as plain sequence would lose
            # the fact that skipping the body was a decision.
            else_exits = [(identity, "when_false")]
        return identity, [*body_exits, *else_exits]

    def _loop(self, node: ast.stmt, scope: str, enter: str, leave: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        breaks: list[_Exit] = []
        self._loops.append((identity, breaks))
        body_entry, body_exits = self.sequence(getattr(node, "body", []), scope)
        self._loops.pop()

        if body_entry is not None:
            self.graph.edge(identity, body_entry, enter)
        for source, _ in body_exits:
            # The back edge is what makes a loop a loop rather than a list.
            self.graph.edge(source, identity, "repeat")

        exits: list[_Exit] = [(identity, leave), *breaks]
        else_entry, else_exits = self.sequence(getattr(node, "orelse", []), scope)
        if else_entry is not None:
            self.graph.edge(identity, else_entry, leave)
            exits = [*else_exits, *breaks]
        return identity, exits

    def _on_While(self, node: ast.While, scope: str) -> tuple[str, list[_Exit]]:
        return self._loop(node, scope, "when_true", "when_false")

    def _on_For(self, node: ast.For, scope: str) -> tuple[str, list[_Exit]]:
        return self._loop(node, scope, "each_item", "exhausted")

    _on_AsyncFor = _on_For

    def _on_Return(self, node: ast.Return, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        return identity, []

    def _on_Break(self, node: ast.Break, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        if self._loops:
            self._loops[-1][1].append((identity, "next"))
        return identity, []

    def _on_Continue(self, node: ast.Continue, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        if self._loops:
            self.graph.edge(identity, self._loops[-1][0], "repeat")
        return identity, []

    def _on_Try(self, node: ast.Try, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        body_entry, exits = self.sequence(node.body, scope)
        if body_entry is not None:
            self.graph.edge(identity, body_entry, "next")
        for handler in node.handlers:
            handler_entry, handler_exits = self.sequence(handler.body, scope)
            if handler_entry is not None:
                # Any step in the body may raise, so the handler is reachable
                # from the try itself rather than from a particular statement.
                self.graph.edge(identity, handler_entry, "on_error")
                exits = [*exits, *handler_exits]
        else_entry, else_exits = self.sequence(node.orelse, scope)
        if else_entry is not None:
            for source, kind in exits:
                self.graph.edge(source, else_entry, kind)
            exits = else_exits
        final_entry, final_exits = self.sequence(node.finalbody, scope)
        if final_entry is not None:
            for source, kind in exits:
                self.graph.edge(source, final_entry, kind)
            exits = final_exits
        return identity, exits

    def _on_With(self, node: ast.With, scope: str) -> tuple[str, list[_Exit]]:
        identity = self.graph.step(node, scope)
        body_entry, exits = self.sequence(node.body, scope)
        if body_entry is not None:
            self.graph.edge(identity, body_entry, "next")
        else:
            exits = [(identity, "next")]
        return identity, exits

    _on_AsyncWith = _on_With


def analyze(source: str, *, module: str = "", file: str = "<source>") -> dict[str, Any]:
    """Return the control-flow graph of one module.

    Parameters
    ----------
    source : str
        The module's text.
    module : str, optional
        Its dotted import path, used to mint step identities.
    file : str, optional
        A label for spans.

    Returns
    -------
    dict
        ``steps`` carry a neutral node type, the callee when the step is a
        call, the condition when it is a branch or loop, and a span.
        ``edges`` are typed by the reason control moves.

    Notes
    -----
    Each function gets its own subgraph, since control does not flow between
    them without a call. Steps are statements rather than expressions: that is
    the granularity a plan is written at, and it keeps the graph small enough
    to render.

    A span is on every step, so a trace joins to this graph without any
    further machinery.
    """
    graph = _Graph(module, file)
    tree = ast.parse(source)
    builder = _Builder(graph)
    builder.sequence(tree.body, "")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            builder.sequence(node.body, node.name)
    return {"file": file, "module": module, "steps": graph.steps, "edges": graph.edges}


#: Every reason control moves. Emitted as a predicate rather than as a
#: reified edge node, because a store is the consumer and
#: `?loop awl:when_true+ ?step` is the query this graph exists to serve.
EDGE_KINDS = ("next", "when_true", "when_false", "each_item", "exhausted", "repeat", "on_error")


def as_document(graph: dict[str, Any]) -> dict[str, Any]:
    """Turn an analysed graph into JSON-LD nodes with typed edge predicates.

    Parameters
    ----------
    graph : dict
        The output of :func:`analyze`.

    Returns
    -------
    dict
        A ``@graph`` of steps, each carrying its outgoing edges as properties
        named for the reason control moves.

    Notes
    -----
    Reifying an edge as its own node would need two joins to cross one edge
    and would put ``repeat`` and ``when_true`` behind a literal comparison. A
    predicate per reason keeps a path expression usable, which is what makes
    "every step reachable while this test holds" a one-line query.
    """
    outgoing: dict[str, dict[str, list[str]]] = {}
    for edge in graph["edges"]:
        outgoing.setdefault(edge["from"], {}).setdefault(edge["kind"], []).append(edge["to"])

    nodes = []
    for step in graph["steps"]:
        node: dict[str, Any] = {
            "@id": step["id"],
            "_type": "Step",
            "node_type": step["node_type"],
            "parser_type_name": step["parser_type_name"],
            "span": step["span"],
        }
        for key in ("callee", "condition", "condition_reads", "scope"):
            if step.get(key):
                node[key] = step[key]
        for kind, targets in outgoing.get(step["id"], {}).items():
            node[kind] = [{"@id": target} for target in targets]
        nodes.append(node)
    return {"@graph": nodes}
