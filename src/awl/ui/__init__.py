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

from awl import compact, editor, pipeline

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
        self.edits.extend(patches)
        return self.document

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
            self.edits.append({**span, "text": editor._unparse(_without_span(rebuilt))})
            return self.document

        raise LookupError(
            f"nothing at {path} carries a span of its own, so the edit could not be located. "
            "Only a value has one: changing a name or a signature is a structural edit, and "
            "rebuilding the node holding it would reformat everything inside it."
        )

    def to_source(self) -> str:
        """Return the source with every edit applied, by span.

        Regenerating from the document would reformat the whole file and drop
        its comments. Patching by span touches only what was edited, which is
        the difference between an editor and a code generator.
        """
        from awl import writeback

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
