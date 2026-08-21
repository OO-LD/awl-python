"""Reaching definitions and def-use edges: the backbone of value provenance.

An ordered syntax tree says what the code *is*. It does not say where a value
came from, because nothing links a name being read to the binding that produced
it. This module adds that link, which is what makes the ``ast`` profile able to
answer provenance questions rather than only structural ones.

Two properties worth stating, because both were initially got wrong.

**Provenance does not need typing.** Following a value back through
``linear["strain"].pint.to_base_units().pint.magnitude`` never requires knowing
what those calls mean, only that the value flowed through them. Chains that are
impossible to type are ordinary to trace.

**A name may have several reaching definitions.** Taking only the most recent
one silently drops a dependency whenever a value is assigned in both arms of a
branch, so definitions are tracked as sets and merged at every join.
"""

from __future__ import annotations

import ast
from typing import Any

from awl.ids import mint

__all__ = ["analyze"]

#: How many times a loop body is replayed. Twice is enough to pick up a
#: loop-carried dependency (a name read on one pass and rebound on the
#: previous one) without iterating to a fixpoint, which would cost more than
#: the extra precision is worth here.
_LOOP_PASSES = 2


def _span(node: ast.AST, file: str) -> dict[str, Any] | None:
    """Return the source span of *node*, or None when it carries no position."""
    lineno = getattr(node, "lineno", None)
    if lineno is None:
        return None
    return {
        "file": file,
        "startLine": lineno,
        "startCol": getattr(node, "col_offset", 0),
        "endLine": getattr(node, "end_lineno", None) or lineno,
        "endCol": getattr(node, "end_col_offset", None) or 0,
    }


def _dotted(node: ast.AST | None) -> str | None:
    """Return the dotted name a node denotes, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _attribute_path(node: ast.AST) -> list[str] | None:
    """Return the attribute chain rooted in a plain name, or None."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return list(reversed(parts))


def _names_read(node: ast.AST | None) -> list[str]:
    """Return every name read inside *node*, in source order.

    A subscript, an attribute chain and a call all reduce to the names they
    touch, which is exactly what a provenance edge needs: the value flowed
    through those, whatever they mean.
    """
    if node is None:
        return []
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            found.append(child.id)
    return found


def _bound_names(target: ast.AST) -> list[str]:
    """Return the plain names a assignment target binds.

    Handles tuple and starred unpacking, so ``slope, *_ = linregress(...)``
    binds ``slope``. Attribute and subscript targets bind no name; they are
    recorded separately as member writes.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _bound_names(element)]
    return []


class _Analysis:
    """Accumulates definitions and member writes for one module."""

    def __init__(self, module: str, file: str) -> None:
        self.module = module
        self.file = file
        self.definitions: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self._counter = 0

    def define(
        self,
        name: str,
        *,
        kind: str,
        scope: str,
        node: ast.AST,
        depends_on: frozenset[str] = frozenset(),
        produced_by: str | None = None,
    ) -> str:
        """Record a binding and return its identity."""
        self._counter += 1
        identity = mint(
            scheme="py",
            module=self.module,
            symbol=f"{scope}.{name}" if scope else name,
            disambiguator=str(self._counter),
        )["iri"]
        self.definitions.append({
            "id": identity,
            "name": name,
            "kind": kind,
            "scope": scope,
            "span": _span(node, self.file),
            "producedBy": produced_by,
            "dependsOn": sorted(depends_on),
        })
        return identity

    def write(
        self,
        path: list[str],
        *,
        scope: str,
        node: ast.AST,
        depends_on: frozenset[str],
        produced_by: str | None,
    ) -> None:
        """Record an assignment to an attribute path."""
        self.writes.append({
            "path": ".".join(path),
            "scope": scope,
            "span": _span(node, self.file),
            "producedBy": produced_by,
            "dependsOn": sorted(depends_on),
        })


Environment = dict[str, frozenset[str]]


def _merge(left: Environment, right: Environment) -> Environment:
    """Union the reaching definitions of two control-flow paths.

    Taking one side would drop a dependency for any name bound in both arms,
    which is the failure this analysis exists to avoid.
    """
    merged: Environment = dict(left)
    for name, definitions in right.items():
        merged[name] = merged.get(name, frozenset()) | definitions
    return merged


class _Walker:
    """Walks statements in source order, threading reaching definitions."""

    def __init__(self, analysis: _Analysis) -> None:
        self.analysis = analysis

    def reads(self, node: ast.AST | None, environment: Environment) -> frozenset[str]:
        """Return the definitions reached by every name read in *node*."""
        reaching: set[str] = set()
        for name in _names_read(node):
            reaching |= environment.get(name, frozenset())
        return frozenset(reaching)

    def block(self, body: list[ast.stmt], environment: Environment, scope: str) -> Environment:
        """Walk a statement list, returning the environment after it."""
        for statement in body:
            environment = self.statement(statement, environment, scope)
        return environment

    def statement(self, node: ast.stmt, environment: Environment, scope: str) -> Environment:
        handler = getattr(self, f"_on_{type(node).__name__}", None)
        if handler is not None:
            return handler(node, environment, scope)
        return environment

    # Bindings -----------------------------------------------------------

    def _assign(
        self,
        targets: list[ast.expr],
        value: ast.expr | None,
        node: ast.stmt,
        environment: Environment,
        scope: str,
        kind: str = "assign",
    ) -> Environment:
        depends = self.reads(value, environment)
        produced = _dotted(value.func) if isinstance(value, ast.Call) else None
        environment = dict(environment)
        for target in targets:
            names = _bound_names(target)
            for name in names:
                identity = self.analysis.define(
                    name,
                    kind=kind,
                    scope=scope,
                    node=node,
                    depends_on=depends,
                    produced_by=produced,
                )
                environment[name] = frozenset({identity})
            if not names:
                path = _attribute_path(target)
                if path is not None and len(path) > 1:
                    self.analysis.write(
                        path,
                        scope=scope,
                        node=node,
                        depends_on=depends | environment.get(path[0], frozenset()),
                        produced_by=produced,
                    )
        return environment

    def _on_Assign(self, node, environment, scope):
        return self._assign(node.targets, node.value, node, environment, scope)

    def _on_AnnAssign(self, node, environment, scope):
        return self._assign([node.target], node.value, node, environment, scope)

    def _on_AugAssign(self, node, environment, scope):
        # Reads its target as well as its value: `i += 1` depends on `i`.
        depends = self.reads(node.value, environment) | environment.get(_dotted(node.target) or "", frozenset())
        environment = dict(environment)
        for name in _bound_names(node.target):
            environment[name] = frozenset({
                self.analysis.define(name, kind="augmented", scope=scope, node=node, depends_on=depends)
            })
        return environment

    def _on_Expr(self, node, environment, scope):
        return environment

    def _on_Return(self, node, environment, scope):
        return environment

    # Control flow -------------------------------------------------------

    def _on_If(self, node, environment, scope):
        condition = self.reads(node.test, environment)
        then_branch = self.block(node.body, dict(environment), scope)
        else_branch = self.block(node.orelse, dict(environment), scope)
        merged = _merge(then_branch, else_branch)
        # The condition is a dependency of everything the branch produced.
        for definition in self.analysis.definitions:
            if definition["id"] in _new_ids(environment, merged):
                definition["dependsOn"] = sorted(set(definition["dependsOn"]) | condition)
        return merged

    def _loop(self, node, environment, scope, target=None, iterable=None):
        if target is not None and iterable is not None:
            depends = self.reads(iterable, environment)
            environment = dict(environment)
            for name in _bound_names(target):
                environment[name] = frozenset({
                    self.analysis.define(
                        name,
                        kind="loop",
                        scope=scope,
                        node=node,
                        depends_on=depends,
                        produced_by=_dotted(iterable.func) if isinstance(iterable, ast.Call) else None,
                    )
                })
        for _ in range(_LOOP_PASSES):
            environment = _merge(environment, self.block(node.body, dict(environment), scope))
        return _merge(environment, self.block(node.orelse, dict(environment), scope))

    def _on_For(self, node, environment, scope):
        return self._loop(node, environment, scope, node.target, node.iter)

    _on_AsyncFor = _on_For

    def _on_While(self, node, environment, scope):
        return self._loop(node, environment, scope)

    def _on_With(self, node, environment, scope):
        for item in node.items:
            if item.optional_vars is not None:
                environment = self._assign(
                    [item.optional_vars], item.context_expr, node, environment, scope, kind="with"
                )
        return self.block(node.body, environment, scope)

    _on_AsyncWith = _on_With

    def _on_Try(self, node, environment, scope):
        after = self.block(node.body, dict(environment), scope)
        for handler in node.handlers:
            after = _merge(after, self.block(handler.body, dict(environment), scope))
        after = _merge(after, self.block(node.orelse, dict(after), scope))
        return self.block(node.finalbody, after, scope)

    # Scopes -------------------------------------------------------------

    def _on_FunctionDef(self, node, environment, scope):
        inner: Environment = {}
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg else []),
            *([arguments.kwarg] if arguments.kwarg else []),
        ):
            inner[argument.arg] = frozenset({
                self.analysis.define(argument.arg, kind="parameter", scope=node.name, node=argument)
            })
        self.block(node.body, inner, node.name)
        return environment

    _on_AsyncFunctionDef = _on_FunctionDef

    def _on_ClassDef(self, node, environment, scope):
        return environment


def _new_ids(before: Environment, after: Environment) -> set[str]:
    """Return the definition identities introduced between two environments."""
    seen: set[str] = set()
    for name, definitions in after.items():
        seen |= definitions - before.get(name, frozenset())
    return seen


def analyze(source: str, *, module: str = "", file: str = "<source>") -> dict[str, Any]:
    """Return the def-use graph of one module.

    Parameters
    ----------
    source : str
        The module's text.
    module : str, optional
        Its dotted import path, used to mint definition identities.
    file : str, optional
        A label for spans.

    Returns
    -------
    dict
        ``definitions`` are name bindings, each with the definitions it
        ``dependsOn`` and the callee that ``producedBy`` it. ``writes`` are
        assignments to attribute paths, carrying the same two edges.

    Notes
    -----
    Definitions are tracked as sets and merged at every control-flow join, so a
    name bound in both arms of a branch reaches its uses through both. A loop
    body is replayed twice, which picks up a loop-carried dependency without
    iterating to a fixpoint.

    Nothing here requires a type. That is the point: a chain that cannot be
    typed can still be traced.
    """
    analysis = _Analysis(module, file)
    tree = ast.parse(source)
    walker = _Walker(analysis)
    walker.block(tree.body, {}, "")
    return {
        "file": file,
        "module": module,
        "definitions": analysis.definitions,
        "writes": analysis.writes,
    }
