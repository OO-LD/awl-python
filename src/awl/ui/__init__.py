"""What every editor variant shares: the model, the operations, the overlay.

Three canvases are built against this, and the point of building three is to
settle a design question with evidence rather than taste: whether a procedure
reads better as nested control flow or as a dataflow graph, and whether a
typed parameter form belongs inside a node or beside it. A comparison is only
worth anything if the thing being compared is the paradigm, so everything
below the canvas is here and is identical for all three.

A variant supplies a canvas and a form. It supplies no model, no edit
semantics and no validation: those are :mod:`awl.editor`, and a variant that
reimplemented them would be measuring its own reimplementation.

The widget speaks anywidget, so one component serves the notebook, Panel
through ``AnyWidgetComponent``, and JupyterLite.
"""

from __future__ import annotations

from typing import Any

from awl import compact, controlflow, editor, facts, pipeline
from awl.resolve import resolve

__all__ = ["OPERATIONS", "VARIANTS", "EditorModel", "load"]

#: The edits a canvas may make. Each returns a new document and the source
#: patch that would make the same change, so a variant needs no edit semantics
#: of its own.
OPERATIONS = ("set_literal", "add_step", "delete_step", "reorder")

#: The canvas and form pairing each variant is testing.
#:
#: The third is not a hedge between the other two. React Flow with RJSF is the
#: path of least resistance in React and pays for it with a permanent uiSchema
#: mapping; pairing React Flow with jedison asks whether the schema form can be
#: kept schema-driven while the canvas stays React, which is the question the
#: first two together cannot answer.
VARIANTS = {
    "blockly": ("Blockly", "jedison", "control flow as nested blocks"),
    "reactflow": ("React Flow", "RJSF", "dataflow as a node graph"),
    "reactflow_jedison": ("React Flow", "jedison", "dataflow as a node graph, schema-driven form"),
}


class EditorModel:
    """A document being edited, and the source patches that would apply it.

    Every operation returns a new document and appends the patch that would
    make the same change to the file. Holding both is what lets an editor
    show a change immediately and still write it back by span, touching
    nothing else in the file.

    Parameters
    ----------
    source : str
        The module's text.
    module : str, optional
        Its dotted import path.
    file : str, optional
        A label for spans.
    index : dict, optional
        Module path to source, for what this module imports from.

    Attributes
    ----------
    document : dict
        The compact document, with spans, because an edit is written back by
        span and a trace is laid over the same key.
    edits : list of dict
        Every patch produced so far, oldest first.
    """

    def __init__(
        self,
        source: str,
        *,
        module: str = "",
        file: str = "<source>",
        index: dict[str, str] | None = None,
    ) -> None:
        self.source = source
        self.module = module
        self.file = file
        self.index = index or {}
        self.document = pipeline.to_compact(source, module=module, file=file, index=self.index, spans=True)
        self.edits: list[dict[str, Any]] = []
        # The plan is the flow a canvas draws, and it already carries the scope
        # each step belongs to, so a level is a scope rather than a structure
        # this has to build.
        self.plan = controlflow.analyze(source, module=module, file=file)
        self.facts = facts.extract(source, module=module, file=file)
        self.names = resolve(self.facts)
        self._descended: dict[str, EditorModel] = {}

    def apply(self, operation: str, **arguments: Any) -> dict[str, Any]:
        """Run one edit operation and keep its patch.

        Parameters
        ----------
        operation : str
            One of :data:`OPERATIONS`.
        **arguments
            Passed through to that operation.

        Returns
        -------
        dict
            The new document.

        Raises
        ------
        ValueError
            If the operation is not one the editor offers, rather than
            silently doing nothing.
        """
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation!r}; expected one of {list(OPERATIONS)}")
        self.document, patches = getattr(editor, operation)(self.document, **arguments)
        for patch in patches:
            self._record(patch)
        return self.document

    def scopes(self) -> list[dict[str, Any]]:
        """Return the levels this module offers, module scope first.

        Returns
        -------
        list of dict
            ``scope`` and ``steps``, the number of steps at that level.

        Notes
        -----
        A canvas needs somewhere to start, and module scope is usually not it:
        a module is imports and declarations, and the flow worth drawing is
        inside a function. Both canvases built against this reached the same
        dead end, opening at ``""`` and finding a docstring and two imports
        with nothing to descend into.

        The fix is here and not in the plan. A ``def`` is a declaration, not a
        step: making it one so that navigation had something to click would put
        declarations in the ``next`` chain and change what the plan asserts
        about what runs. Which levels exist is a question about the module, and
        this answers it without touching what a level means.
        """
        counts: dict[str, int] = {}
        for step in self.plan["steps"]:
            counts[step.get("scope", "")] = counts.get(step.get("scope", ""), 0) + 1

        found = [{"scope": "", "steps": counts.get("", 0)}]
        for entry in self.facts.get("declarations", []):
            if entry.get("kind") == "function":
                found.append({"scope": entry["name"], "steps": counts.get(entry["name"], 0)})
        return found

    def flow(self, scope: str = "") -> dict[str, Any]:
        """Return one level of the flow: the steps at *scope*, and their edges.

        Parameters
        ----------
        scope : str, optional
            The function whose body to show. ``""`` is the module itself.

        Returns
        -------
        dict
            ``steps`` in source order and ``edges`` between them. An edge is
            ``next``, ``when_true``, ``when_false``, ``each_item``,
            ``exhausted``, ``repeat`` or ``on_error``, which is what a canvas
            draws: two calls in sequence are ``a -> b``, and a conditional or a
            loop is a step of its own between them with edges out of it.

        Notes
        -----
        A level is a scope, and every level is drawn the same way. There is no
        depth limit, because nothing here counts depth: a scope is a name, and
        descending produces another scope.
        """
        here = {step["id"] for step in self.plan["steps"] if step.get("scope", "") == scope}
        return {
            "scope": scope,
            "steps": [step for step in self.plan["steps"] if step["id"] in here],
            "edges": [edge for edge in self.plan["edges"] if edge.get("from") in here and edge.get("to") in here],
            "sublevels": self.sublevels(scope),
        }

    def sublevels(self, scope: str = "") -> list[dict[str, Any]]:
        """Return the levels declared at *scope*, as blocks to render.

        Parameters
        ----------
        scope : str, optional
            The level being drawn.

        Returns
        -------
        list of dict
            ``name``, ``scope``, ``steps`` and ``span`` for each function
            declared here.

        Notes
        -----
        A level draws what runs at it, and a declaration does not run, so
        neither canvas had anything to show for ``procedure`` while standing on
        the module that declares it. That made a module a dead end and put the
        only way in behind a list beside the canvas.

        A declaration is still not a step: it has no place in the ``next``
        chain and nothing flows through it. It is a block that stands for a
        level, which is a different thing on the canvas and is why it is a
        different key here.
        """
        found = []
        for entry in self.facts.get("declarations", []):
            if entry.get("kind") != "function":
                continue
            if (entry.get("scope") or "") != scope:
                continue
            span = entry.get("span") or {}
            found.append({
                "name": entry["name"],
                "scope": entry["name"],
                "steps": sum(1 for step in self.plan["steps"] if step.get("scope") == entry["name"]),
                "span": [
                    span.get("start_line"),
                    span.get("start_col"),
                    span.get("end_line"),
                    span.get("end_col"),
                ],
            })
        return found

    def set_source(self, text: str) -> dict[str, Any]:
        """Replace the source and rebuild everything drawn from it.

        Parameters
        ----------
        text : str
            The module's new text.

        Returns
        -------
        dict
            ``ok`` and either the new ``document`` or the ``error`` that
            stopped it, with ``line`` and ``offset`` when the parser gave them.

        Notes
        -----
        Editing runs both ways or the source pane is a read-only echo. What
        makes it safe is that a failure changes nothing: a half-typed edit does
        not parse, and a canvas rebuilt from a partial tree would flicker
        through states the file was never in.

        Pending patches are dropped, because they address offsets in the text
        being replaced. Keeping them would apply an old edit at a new position.
        """
        import ast

        try:
            ast.parse(text)
        except SyntaxError as error:
            return {"ok": False, "error": error.msg, "line": error.lineno, "offset": error.offset}

        self.source = text
        self.document = pipeline.to_compact(text, module=self.module, file=self.file, index=self.index, spans=True)
        self.plan = controlflow.analyze(text, module=self.module, file=self.file)
        self.facts = facts.extract(text, module=self.module, file=self.file)
        self.names = resolve(self.facts)
        self.edits = []
        self._descended = {}
        return {"ok": True, "document": self.document}

    def run(
        self,
        entry: str,
        *arguments: Any,
        environment: dict[str, Any] | None = None,
        modules: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a function in this module under instrumentation.

        Parameters
        ----------
        entry : str
            The function to call.
        *arguments
            Passed to it.
        environment : dict, optional
            Names to provide before the module runs.
        modules : dict, optional
            Modules to stand in for the duration of the run, by import path.
            A procedure drives hardware that is not attached, and its imports
            run before any of its statements do, so a name in *environment*
            never gets the chance to help. The caller says what
            ``battery.device`` is for this run; nothing here guesses, and
            nothing is left installed afterwards.

        Returns
        -------
        dict
            ``ok``, and either the per-step ``overlay`` or the ``error`` that
            stopped the run, which is itself worth drawing: a step that raised
            is a fact about the procedure.

        Notes
        -----
        The overlay is joined to the plan by span, the key the canvas was drawn
        from, so a variant lays it over the nodes it already has.
        """
        import sys

        namespace: dict[str, Any] = dict(environment or {})
        compiled = compile(self.source, self.file, "exec")
        borrowed = {name: sys.modules.get(name) for name in modules or {}}
        try:
            sys.modules.update(modules or {})
            exec(compiled, namespace)  # noqa: S102 - running the module is the point
            target = namespace[entry]
        except Exception as error:
            return {"ok": False, "error": f"{type(error).__name__}: {error}"}
        finally:
            for name, held in borrowed.items():
                if held is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = held

        failure: list[str] = []

        def call() -> None:
            try:
                target(*arguments)
            except Exception as error:
                failure.append(f"{type(error).__name__}: {error}")

        from awl.execution import join
        from awl.trace import trace

        events = trace(call)
        overlay = join(self.plan, events)
        return {"ok": not failure, "overlay": overlay, "error": failure[0] if failure else None}

    def opens(self, step: dict[str, Any]) -> tuple[str, str] | None:
        """Return the module and scope a step descends into, or None.

        Parameters
        ----------
        step : dict
            A step from :meth:`flow`.

        Returns
        -------
        tuple or None
            ``(module, scope)`` when the step calls a function whose source is
            available, so the next level can be drawn. ``None`` when it does
            not call anything, or calls something this run cannot see.

        Notes
        -----
        The distinction is worth showing rather than hiding. A call into a
        library that was never read is not the same as a call into a function
        with an empty body, and a canvas that draws both as leaves says they
        are.
        """
        callee = step.get("callee")
        if not callee:
            return None
        identity = self._identity(callee)
        if identity is None:
            return None
        module, symbol = identity
        if module != self.module and module not in self.index:
            return None
        source = self.source if module == self.module else self.index[module]
        return (module, symbol) if _declares(source, symbol) else None

    def descend(self, step: dict[str, Any]) -> EditorModel | None:
        """Return the model holding the level a step opens into, or None.

        The same class, so every level offers the same operations: this is one
        principle applied at each depth rather than a special case for the
        first.
        """
        opened = self.opens(step)
        if opened is None:
            return None
        module, _scope = opened
        if module == self.module:
            return self
        if module not in self._descended:
            self._descended[module] = EditorModel(self.index[module], module=module, file=module, index=self.index)
        return self._descended[module]

    def _identity(self, name: str) -> tuple[str, str] | None:
        """Return the module and symbol a local name resolves to."""
        for binding in self.names["bindings"]:
            if binding.get("local_name") != name:
                continue
            identity = binding.get("identity") or {}
            if identity.get("module") and identity.get("symbol"):
                return identity["module"], identity["symbol"]
        return None

    def set_value(self, path: list[Any], value: Any) -> dict[str, Any]:
        """Set a value the canvas has selected, and record how to write it back.

        Parameters
        ----------
        path : list
            Keys and indices locating the value in the document.
        value : Any
            What to put there.

        Returns
        -------
        dict
            The new document.

        Raises
        ------
        LookupError
            If nothing in the document carries a span for that value, since a
            patch that cannot be located would have to rewrite the file.

        Notes
        -----
        Two cases, and a canvas should not have to know which it is holding.

        A literal node carries its own span, so the patch replaces exactly it.
        A **collapsed** constructor does not: its fields are bare values in a
        node that stands for a whole call, so there is nothing to point at one
        of them. That node is rebuilt into the call it came from and the patch
        replaces the call. Only the call is reformatted, and the rest of the
        line is untouched, which is the property write-back exists for.
        """
        from awl import writeback

        # The holder is a list as often as it is a node: an argument is
        # selected by position, a field by name, and a canvas has no reason to
        # tell them apart.
        holder = _descend(self.document, path[:-1])
        try:
            target = holder[path[-1]]
        except (KeyError, IndexError, TypeError):
            target = None

        if isinstance(target, dict) and "span" in target:
            span = writeback.offsets(self.source, target["span"])
            return self.apply("set_literal", path=path, value=value, span=span)

        if _is_collapsed(holder) and "span" in holder:
            rebuilt = {**holder, path[-1]: value}
            span = writeback.offsets(self.source, holder["span"])
            self.document = _replace(self.document, path[:-1], rebuilt)
            self._record({**span, "text": editor._unparse(_without_span(rebuilt))})
            return self.document

        raise LookupError(
            f"nothing at {path} carries a span of its own, so the edit could not be located. "
            "Only a value has one: changing a name or a signature is a structural edit, and "
            "rebuilding the node holding it would reformat everything inside it."
        )

    def _record(self, patch: dict[str, Any]) -> None:
        """Keep a patch, replacing any earlier one over the same range.

        Editing one thing twice produces the same span twice, and two patches
        over one range overlap, so appending raised instead of writing the
        second edit. The last one wins, which is what editing something twice
        means.

        An insertion is left alone. It is zero-width, so two of them at one
        offset do not overlap and both belong: adding two steps at the same
        point is two steps, not the second replacing the first.

        A structural patch carries no span at all. It names a path and an
        operation, because moving a statement is not a range of characters:
        span splicing has no opinion about which comment belongs to which
        statement, so a moved node could not carry its own trivia. Reading a
        span off one raised, which made every structural operation
        unreachable through this class.
        """
        if patch.get("kind") == "structural":
            self.edits.append(patch)
            return
        if patch["start"] < patch["end"]:
            self.edits = [
                edit for edit in self.edits if not (edit["start"] == patch["start"] and edit["end"] == patch["end"])
            ]
        self.edits.append(patch)

    def structural(self) -> list[dict[str, Any]]:
        """Return the pending patches span splicing cannot apply."""
        return [edit for edit in self.edits if edit.get("kind") == "structural"]

    def to_source(self) -> str:
        """Return the source with every edit applied, by span.

        Regenerating from the document would reformat the whole file and drop
        its comments. Patching by span touches only what was edited, which is
        the difference between an editor and a code generator.

        Raises
        ------
        NotImplementedError
            If a structural edit is pending. Adding, deleting or moving a
            statement is not a range of characters, and nothing yet routes one
            through a concrete-syntax rewrite, so there is no way to apply it
            without reformatting. :meth:`regenerate` will produce the code and
            lose the file's comments and layout, which is a choice the caller
            should make rather than find out about afterwards.
        """
        from awl import writeback

        pending = self.structural()
        if pending:
            operations = ", ".join(sorted({str(edit.get("operation")) for edit in pending}))
            raise NotImplementedError(
                f"{len(pending)} structural edit(s) pending ({operations}); span splicing cannot apply them. "
                "Use regenerate(), which reformats the file and drops its comments."
            )
        return writeback.apply_edits(self.source, self.edits) if self.edits else self.source

    def regenerate(self) -> str:
        """Return the document unparsed, ignoring the original formatting."""
        import ast

        return ast.unparse(ast.fix_missing_locations(compact.decode(self.document)))

    def overlay(self, call) -> dict[str, Any]:
        """Run *call* under instrumentation and return what each step did.

        Joined to the plan by span, which is the same key the canvas draws
        with, so a variant lays the result over the nodes it already has.
        """
        return pipeline.trace_run(self.source, call, module=self.module, file=self.file)


def _declares(source: str, symbol: str) -> bool:
    """Return whether *source* declares a function called *symbol*."""
    import ast

    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == symbol
        for node in ast.walk(ast.parse(source))
    )


def _descend(doc: Any, path: list[Any]) -> Any:
    """Return the node a path names."""
    for step in path:
        doc = doc[step]
    return doc


def _replace(doc: Any, path: list[Any], node: Any) -> Any:
    """Return a copy of *doc* with the node at *path* replaced."""
    import copy

    out = copy.deepcopy(doc)
    if not path:
        return node
    _descend(out, path[:-1])[path[-1]] = node
    return out


def _is_collapsed(node: Any) -> bool:
    """Return whether *node* is a collapsed constructor.

    Its ``@type`` is a list: a class name and any co-types. A syntax node
    names one type, so the two are told apart by shape rather than by a flag.
    """
    return isinstance(node, dict) and isinstance(node.get("@type"), list)


def _without_span(node: dict[str, Any]) -> dict[str, Any]:
    """Return *node* with its span dropped, ready to be unparsed."""
    return {key: value for key, value in node.items() if key != "span"}


def load(source: str, **options: Any) -> EditorModel:
    """Return an :class:`EditorModel` for *source*."""
    return EditorModel(source, **options)


def sample() -> EditorModel:
    """Return a model over the procedure every variant opens on.

    One sample for all three, so a difference on screen is a difference between
    the canvases. It is a real module in this package rather than a fixture
    string, so the linter and the type checker keep it valid, and it imports
    nothing, so the run button runs it with no stand-ins.
    """
    from pathlib import Path

    path = Path(__file__).with_name("sample.py")
    # The real path, not a label. The tracer reads the file to work out which
    # loop a frame is in and which way a branch went, so a name that is not on
    # disk costs every iteration count and every branch outcome: the overlay
    # still says a step ran, and can no longer say how often or which way.
    return EditorModel(path.read_text(encoding="utf-8"), module="awl.ui.sample", file=str(path))
