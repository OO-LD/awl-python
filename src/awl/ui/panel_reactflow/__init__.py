"""The fifth canvas: React Flow through Panel, with the form inside the node.

The first four all put the typed parameter form *beside* the canvas, and all
four were faulted for it. Not because a side panel is ugly: because a form that
lives beside the canvas makes the canvas a picture of the program and the panel
the program, and a reader then has to hold a selection in their head to know
which node the numbers on the right belong to.

``panel-reactflow`` takes a ``view`` on a node, and a view is any Panel object.
So ``ChargeParam(target_voltage=4.2, c_rate=0.35)`` is drawn as a node carrying
two :class:`panel.widgets.FloatInput`\\ s, and editing one of them is
:meth:`~awl.ui.EditorModel.set_value` on the field it is labelled with. There is
no side panel in this variant at all, and nothing is selected to make a form
appear.

The layout is Sequential Workflow Designer's, rebuilt on React Flow because
React Flow lays nothing out and that makes its geometry a choice rather than a
default. A loop is a bounded region with its body inside it; an ``if`` is a
``then`` column beside an ``else`` column; a drag from the toolbox lights up the
strip it would land on. What the layout expresses, it does not also draw: a
loop's ``repeat`` is what the region around the body already says, and drawing
an arc as well said it twice. Every edge is still read from
``flow(scope)["edges"]`` and from nothing else, and which ones the layout
expresses is recorded rather than ignored, so a canvas that stopped reading them
would look the same and would fail its tests.

Beside the canvas is the module in Monaco, with ty checking it. That is a real
cost and it is measured rather than argued about: the two together are about
18.7 MB, most of it the type checker as WebAssembly, against a comparison whose
previous heaviest page was 766 kB. What it buys is the thing a source pane could
not do before, which is answer a question about the program: a name that does
not type-check is underlined where it is written, hovering one says what it was
inferred to be, and completion offers a member that only something which read
the annotations could know about.

Every block also carries its own comment. ``ast`` has no comment node, so the
compact document has none either and a note is read off the source the block
covers, by :meth:`~awl.ui.EditorModel.trivia`, which is the model's job and not
this canvas's; it is written back the way a literal is, by span. Structural
edits still regenerate the module and still lose every comment in it, and the
warning that says so counts what went rather than claiming it in advance, which
matters more now that comments are something a reader writes here.

Under all of it is a console. A run produces output, a failure and a count per
step, and a notice one line long can hold one of the three.

Panel is a hard dependency and that is not free: the other four are anywidgets
and run in a notebook cell with a kernel of any kind, and this needs a Bokeh
server or a Pyodide runtime. What it buys is a wheel with its JavaScript already
built, which is the other thing this variant was chosen to test.
"""

from __future__ import annotations

import contextlib
import copy
import html
import io
import os
from pathlib import Path
from typing import Any

import panel as pn
import param

from awl import pipeline, ui
from awl.ui.panel_reactflow import components, layout, tree

__all__ = ["TOOLBOX", "PanelReactFlowEditor", "open_sample", "serve", "ty_assets"]

#: Where the source pane's type checker is mounted, when there is one.
TY_ROUTE = "ty-wasm"

#: What may be dropped onto the canvas, and the Python each entry stands for.
#:
#: A template rather than a hand-built compact node: the node ``add_step`` wants
#: is what the pipeline produces from source, so writing the source and letting
#: the pipeline encode it keeps one definition of what a statement is. A palette
#: written as literal ``{"@type": ...}`` dicts would be a second encoder to keep
#: in step with the first.
TOOLBOX: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "Statements",
        (
            ("assignment", "assignment", "value = 0"),
            # `rest(600)` and `i += 1` name things the scope they land in may
            # not have, and where it does not they raise `NameError` on the
            # next run: a line number, a name, and one undo. That is a
            # different failure from the loop below, which raised nothing at
            # all and took the process with it, and only the second one is
            # worth spending a template on.
            ("call", "call", "rest(600)"),
            ("increment", "increment", "i += 1"),
            ("return", "return", "return None"),
        ),
    ),
    (
        "Containers",
        (
            # `while False:`, and not the `while i < 10:` this shipped with. A
            # loop reaches the canvas before its condition does, the run button
            # is one click away, and `i` is whatever the surrounding body left
            # it at: dropped into a body that never touches `i`, this took the
            # whole process down and needed a restart.
            ("loop", "while loop", "while False:\n    pass"),
            ("branch", "if", "if value > 0:\n    pass"),
        ),
    ),
)

#: The node types React Flow is told about. Handles are named rather than
#: positional because the layout decides where an edge leaves and arrives:
#: ``in`` and ``out`` are the top and the bottom of a block, and ``back`` and
#: ``tail`` are the right-hand side, which is where an edge the layout cannot
#: express has to run.
_HANDLES: dict[str, tuple[list[str | dict[str, str]], list[str | dict[str, str]]]] = {
    "step": (["in", "back"], ["out", "tail"]),
    "opens": (["in", "back"], ["out", "tail"]),
    "return": (["in", "back"], ["out", "tail"]),
    "class": (["in", "back"], ["out", "tail"]),
    "import": (["in", "back"], ["out", "tail"]),
    "level": (["in", "back"], ["out", "tail"]),
    "loop": (["in", "back"], ["out", "tail"]),
    "branch": (["in", "back"], ["out", "tail"]),
    "lane": ([], []),
    "zone": ([], []),
}

#: How each kind of node is painted. The container tints are what makes a region
#: a region: a dashed outline alone reads as a selection, not as an enclosure.
_STYLE: dict[str, dict[str, Any]] = {
    "step": {"background": "#ffffff", "border": "1px solid #cbd5e1", "borderRadius": "7px"},
    "opens": {"background": "#ffffff", "border": "1px solid #6366f1", "borderRadius": "7px"},
    "return": {"background": "#fff7ed", "border": "1px solid #fdba74", "borderRadius": "7px"},
    "class": {"background": "#f8fafc", "border": "1px solid #cbd5e1", "borderRadius": "7px"},
    "import": {"background": "#f8fafc", "border": "1px dashed #cbd5e1", "borderRadius": "7px"},
    "level": {"background": "#eef2ff", "border": "1px solid #6366f1", "borderRadius": "7px"},
    "loop": {
        "background": "rgba(99,102,241,.05)",
        "border": "1.5px dashed #6366f1",
        "borderRadius": "12px",
        "boxShadow": "none",
    },
    "branch": {
        "background": "rgba(14,165,233,.05)",
        "border": "1.5px dashed #0ea5e9",
        "borderRadius": "12px",
        "boxShadow": "none",
    },
    "lane": {
        "background": "rgba(255,255,255,.55)",
        "border": "1px dotted #94a3b8",
        "borderRadius": "9px",
        "boxShadow": "none",
    },
    "zone": {"background": "transparent", "border": "0", "boxShadow": "none"},
}

#: What the canvas needs on top of what the library ships.
#:
#: The handle positions are the load-bearing part. ``panel-reactflow`` renders
#: every input on the left and every output on the right, which is the wrong
#: shape for a flow that reads downwards, and React Flow measures a handle's
#: rectangle from the DOM, so moving it in CSS moves where an edge attaches.
#: Zero width and zero height, because React Flow anchors a left handle at the
#: left of its box and a right handle at the right of its box: with no box the
#: two agree, and the connector is vertical rather than three pixels off.
_CANVAS_CSS = """
.react-flow__handle {
  width: 0 !important; height: 0 !important; min-width: 0 !important; min-height: 0 !important;
  border: 0 !important; background: transparent !important; opacity: 0;
}
.react-flow__handle[data-handleid="in"] {
  left: 50% !important; right: auto !important; top: 0 !important; bottom: auto !important; transform: none !important;
}
.react-flow__handle[data-handleid="out"] {
  left: 50% !important; right: auto !important; top: auto !important; bottom: 0 !important; transform: none !important;
}
/* On the container's right edge, level with the header line an arc returns to,
 * so the arrow lands on the line carrying the test rather than on the border of
 * the region. Only an edge the layout cannot express arrives here. */
.react-flow__handle[data-handleid="back"] {
  left: auto !important; right: 0 !important; top: 21px !important; bottom: auto !important; transform: none !important;
}
/* On the block's own right edge, not floated out into the gutter. React Flow
 * runs a step path's vertical leg half way between the two anchors and takes no
 * argument about where: with every block filling its lane, half way between a
 * block's right edge and its container's is the gutter, so the tail can stay
 * attached to the block it leaves. Floated, it started in mid-air. */
.react-flow__handle[data-handleid="tail"] {
  left: auto !important; right: 0 !important;
  top: 50% !important; bottom: auto !important; transform: none !important;
}
.rf-node-content { padding: 0 !important; min-width: 0 !important; }
.rf-node-view-wrapper { width: 100%; height: 100%; }
.react-flow__node { font-family: ui-sans-serif, system-ui; }
/* A container's view is its header, and the region under it is empty on
 * purpose. Left at full height it swallows the pointer over the whole area,
 * and the library marks every view `nowheel`, so a wheel inside a loop stopped
 * zooming the canvas and a drag inside one stopped panning it. Only the header
 * takes the pointer; the rest of the region is a region. */
.react-flow__node-loop .rf-node-content,
.react-flow__node-branch .rf-node-content,
.react-flow__node-lane .rf-node-content { height: auto !important; pointer-events: none; }
.react-flow__node-loop .rf-node-view-wrapper,
.react-flow__node-branch .rf-node-view-wrapper,
.react-flow__node-lane .rf-node-view-wrapper { height: auto !important; pointer-events: auto; }
.react-flow__node-zone { pointer-events: none; }
.react-flow__node-zone .rf-node-content { pointer-events: auto; }
/* A connector is a line, at whatever the canvas is zoomed to. A stroke width is
 * in the canvas's own units and shrinks with the viewport, so a level fitted
 * into the page drew every join at 0.77 of a pixel: pale, anti-aliased and
 * reported as "short stubs" by a reader who could see the two blocks perfectly
 * well. The geometry was right the whole time and the line was half there. */
.react-flow__edge-path { vector-effect: non-scaling-stroke; }
.react-flow__edge-text { font: 600 10px ui-sans-serif, system-ui; fill: #475569; }
.react-flow__edge-textbg { fill: #f8fafc; }
.react-flow__edge.animated .react-flow__edge-path { stroke-dasharray: 6 4; }
.react-flow__attribution { display: none; }
/* One ring, and it is the block's own. The library holds its idea of what is
 * selected in the browser and overwrites whatever the editor sends for a node
 * id it already has, so a selection made from Python could never have shown;
 * leaving the library's own mark on as well would draw two of them whenever a
 * reader clicked. */
.react-flow__node.selected { box-shadow: none; }
/* Set by the block's own view, on the node rather than on the view, because the
 * view is only the block's header: a block carrying typed values is a header
 * above a form and the ring stopped at the bottom of the header line, leaving
 * the fields it belongs to outside it. */
.react-flow__node[data-awl-selected] {
  outline: 2.5px solid #4338ca; outline-offset: 1px; border-radius: 8px;
}
"""

#: The bar above the canvas, the columns beside it, and the console under it.
_SHELL_CSS = """
.awl-bar { border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
.awl-side { border-right: 1px solid #e2e8f0; background: #fbfcfe; }
.awl-pane { background: #f8fafc; }
.awl-pane-head {
  font: 600 11px ui-sans-serif, system-ui; letter-spacing: .06em; text-transform: uppercase;
  color: #64748b; border-bottom: 1px solid #e2e8f0;
}
.awl-bottom { border-top: 1px solid #e2e8f0; background: #f8fafc; }
"""

#: The notice, and the two things it can be besides a notice.
#:
#: On the pane itself, and not on the bar holding it. A stylesheet given to a
#: layout reaches that layout's own shadow root, and every one of these rules
#: matches a span inside the pane's: the refusal a reorder now raises rendered
#: in the same grey as "added", and the reformat warning ran into the word
#: before it with no gap, no border and no colour. Both were asserted on their
#: class names and both passed.
_STATUS_CSS = """
.awl-status { font: 12px ui-monospace, monospace; color: #475569; }
.awl-status-bad { color: #b91c1c; font-weight: 600; }
.awl-status-warn {
  display: inline-block; color: #92400e; background: #fef3c7; border: 1px solid #fcd34d;
  border-radius: 3px; padding: 1px 6px; margin-left: 8px;
}
"""

#: A crumb, which is a button that has to read as text.
#:
#: ``:host()`` rather than a descendant selector: the class is on the widget's
#: host element and the ``button`` is inside its shadow root, so the two are on
#: opposite sides of the boundary and nothing written as ``.awl-crumb button``
#: can match.
_CRUMB_CSS = """
:host(.awl-crumb) button {
  font: 500 12px ui-sans-serif, system-ui !important; border: 0 !important; background: transparent !important;
  color: #4338ca !important; padding: 2px 6px !important; min-height: 0 !important;
}
:host(.awl-crumb-here) button { color: #0f172a !important; font-weight: 700 !important; }
"""

#: The mark between two crumbs. On ``:host``, because colour and font are
#: inherited and that is the one way into a pane whose markup is a shadow root.
_SEPARATOR_CSS = ":host { color: #94a3b8; font: 12px ui-sans-serif, system-ui; }"


def ty_assets() -> Path | None:
    """Return the directory holding ``ty_wasm.js``, or None if there is none.

    Returns
    -------
    pathlib.Path or None
        A directory containing Astral's ty compiled to WebAssembly.

    Notes
    -----
    ty is 17.7 MB of WebAssembly and is not this package's to ship: it is built
    from Astral's repository and lives beside the other playgrounds. The host
    says where, through ``AWL_TY_WASM``; failing that this looks for the
    checkout the build it came from lives in.

    Returning None is a supported state and not a degraded one for the
    requirement that matters: the pane still edits, still highlights, still
    round trips, and still shows the parse error that decides whether the canvas
    is redrawn. Only the type checking is gone, and the pane says so rather than
    pretending a clean file.
    """
    told = os.environ.get("AWL_TY_WASM")
    here = Path(__file__).resolve()
    for candidate in ([Path(told)] if told else []) + [
        parent / "oold-playgrounds" / "ty-playground" / "ty_wasm" for parent in here.parents
    ]:
        if (candidate / "ty_wasm.js").is_file():
            return candidate
    return None


class PanelReactFlowEditor(param.Parameterized):
    """One level of a module, as a React Flow canvas with forms inside its nodes.

    Parameters
    ----------
    model : awl.ui.EditorModel
        The document being edited. Not copied: this is a view of it.
    scope : str, optional
        The level to open on.
    entry : str, optional
        The function the run button calls.
    arguments : tuple, optional
        What to call it with.
    canvas_height : int, optional
        The least the canvas may be. It stretches to whatever the window leaves
        between the bar and the console; this is the floor, for a window too
        short to give it that.
    console_height : int, optional
        How tall the console is.
    pane_width : int, optional
        How wide the source pane opens. The splitter moves it afterwards.

    Attributes
    ----------
    status, error : str
        What just happened, and what went wrong.
    overlay : dict
        The last run, keyed by document path, cleared on every reparse.
    """

    status = param.String(default="")
    error = param.String(default="")
    reformats = param.Boolean(default=False)
    #: What the last write-back cost the file, measured on it rather than
    #: asserted in advance. Empty when nothing was rewritten.
    rewritten = param.String(default="")

    #: How many lines the console keeps. A run writes one per step and a reader
    #: leaves the editor open all afternoon.
    SAID = 400

    #: The narrowest and widest the source pane may be dragged.
    SPLIT = (280, 1000)

    #: How many edits back the undo button reaches. Snapshots are whole module
    #: texts and never leave the server, so the bound is memory rather than
    #: bandwidth.
    HISTORY = 20

    def __init__(
        self,
        model: ui.EditorModel,
        *,
        scope: str = "",
        entry: str = "",
        arguments: tuple[Any, ...] = (),
        canvas_height: int = 556,
        console_height: int = 170,
        pane_width: int = 560,
        ty_url: str = "",
        **options: Any,
    ) -> None:
        super().__init__(**options)
        # The module is always the root of the trail even when the editor opens
        # further in. A navigator whose first entry is where you started is not
        # a navigator: the level above has to be reachable, and the module is
        # the level above every function in it.
        self._stack: list[tuple[ui.EditorModel, str]] = [(model, "")]
        if scope:
            self._stack.append((model, scope))
        self._entry = entry
        self._arguments = tuple(arguments)
        self._history: list[tuple[ui.EditorModel, str]] = []
        self.overlay: dict[str, dict[str, Any]] = {}

        self.tree: tree.Lane = tree.Lane(path=["body"])
        self.boxes: dict[str, tuple[float, float, float, float]] = {}
        self.lane_kinds: dict[str, str] = {}
        #: Which block's outgoing edge the containment expresses rather than
        #: draws, by block id. A loop's ``repeat`` is here and not on the
        #: canvas: the region around the body is what says the body repeats,
        #: and this is what a test reads to prove the plan's edge was seen.
        self.enclosed: dict[str, str] = {}
        #: Where each back edge's vertical leg lands, by edge id. Computed and
        #: not commanded: React Flow shapes the path and this says what it will
        #: be, which is what a test asserts the arc clears the blocks with.
        self.legs: dict[str, float] = {}
        self._blocks: dict[str, tree.Block] = {}
        self._owner: dict[str, str] = {}
        # All three are filled by the first `refresh` and all three are read
        # while it is still running: a node's form asks `_declared` what its
        # class declared, and every view built asks `_select` whether it is the
        # one wearing the ring.
        self._declared: dict[str, dict[str, str]] = {}
        self._views: dict[str, Any] = {}
        self._select: str = ""
        # A rebuild is not a gesture. Replacing the nodes makes the library
        # recompute its derived selection and report that nothing is selected,
        # and taking that at face value wiped the ring off the block an insert
        # had just put it on.
        self._rebuilding = False

        from panel_reactflow import NodeType, ReactFlow

        self.flow = ReactFlow(
            node_types={
                name: NodeType(type=name, label="", inputs=inputs, outputs=outputs)
                for name, (inputs, outputs) in _HANDLES.items()
            },
            nodes=[],
            edges=[],
            # The library's own editors are declined, both of them. Its default
            # is a `SchemaEditor`, which is a `panel-material-ui` form and a
            # `jsoneditor` fallback per node, built whether or not it is ever
            # shown, and this variant's whole claim is that the form is the
            # node's `view`, so a second form behind a gear would be two
            # answers to one question, and the more expensive one is the one
            # nobody asked for.
            default_node_editor=_no_editor,
            default_edge_editor=_no_editor,
            editor_mode="node",
            editable=True,
            enable_connect=False,
            enable_delete=False,
            enable_multiselect=False,
            min_zoom=0.2,
            max_zoom=1.6,
            # Stretched, not sized. A fixed height left the canvas 556 px tall
            # in a 950 px window with the console 211 px below the bottom of it,
            # and the canvas is where the fit-to-view zoom comes from: a level
            # 1330 px tall fitted into 556 is drawn at 0.36, which is what made
            # every connector between two blocks a twelve pixel tick.
            min_height=canvas_height,
            sizing_mode="stretch_both",
            stylesheets=[_CANVAS_CSS],
        )
        self.flow.param.watch(self._selected, "selection")

        self.source_pane = components.SourcePane(
            on_command=self.command, ty_url=ty_url, sizing_mode="stretch_both", stylesheets=[_SHELL_CSS]
        )
        self.splitter = components.Splitter(on_command=self.command, width=7, sizing_mode="stretch_height", margin=0)
        self.console = components.Console(sizing_mode="stretch_both", margin=0)
        self._console_height = console_height
        self._said: list[dict[str, str]] = []
        self._pane = pn.Column(
            pn.pane.HTML("source", css_classes=["awl-pane-head"], margin=(6, 8), sizing_mode="stretch_width"),
            self.source_pane,
            width=pane_width,
            margin=0,
            css_classes=["awl-pane"],
            stylesheets=[_SHELL_CSS],
            sizing_mode="stretch_height",
        )
        self.toolbox = components.Toolbox(
            entries=[
                {"name": name, "items": [{"kind": kind, "label": label, "code": code} for kind, label, code in items]}
                for name, items in TOOLBOX
            ],
            on_command=self.command,
            sizing_mode="stretch_width",
        )
        self._trail = pn.Row(sizing_mode="stretch_width", margin=0, css_classes=["awl-trail"])
        self._status = pn.pane.HTML(
            "",
            sizing_mode="stretch_width",
            margin=(4, 8),
            css_classes=["awl-status-host"],
            stylesheets=[_STATUS_CSS],
        )
        self._run = pn.widgets.Button(
            label="Run", color="primary", height=28, width=64, margin=(4, 4), css_classes=["awl-run"]
        )
        self._run.on_click(lambda _event: self.command({"op": "run"}))
        self._undo = pn.widgets.Button(
            label="Undo", color="light", height=28, width=64, margin=(4, 4), disabled=True, css_classes=["awl-undo"]
        )
        self._undo.on_click(lambda _event: self.command({"op": "undo"}))

        self.refresh(status=f"opened {scope or model.module or 'module'}")

    # -- where the reader is ---------------------------------------------------

    @property
    def model(self) -> ui.EditorModel:
        """The model for the level on screen."""
        return self._stack[-1][0]

    @property
    def scope(self) -> str:
        """The level on screen."""
        return self._stack[-1][1]

    @property
    def selected(self) -> str:
        """The node the canvas is drawing as selected, or ``""``."""
        return self._select

    @property
    def trail(self) -> list[dict[str, str]]:
        """Every level between the module and here, oldest first."""
        return [
            {"module": held.module or "module", "scope": name, "label": name or (held.module or "module")}
            for held, name in self._stack
        ]

    def nesting(self, node_id: str) -> list[dict[str, str]]:
        """Return the containers a block sits inside, outermost first.

        A loop contributes one entry and a branch contributes two, itself and
        the lane, because "inside the ``if``" and "inside its ``else``" are
        different places to be standing, and a navigator that cannot say which
        is not answering the question it exists for. A loop's body is not a
        second place: there is only one of it, so naming it would put
        ``when_true`` in the trail as if it were somewhere to be.
        """
        found: list[dict[str, str]] = []

        def search(lane: tree.Lane, walked: list[dict[str, str]]) -> bool:
            for block in lane.blocks:
                if block.id == node_id or layout.lane_id(lane) == node_id:
                    found.extend(walked)
                    return True
                mine = {"id": block.id, "label": block.label}
                for inner in block.lanes:
                    deeper = [*walked, mine]
                    if len(block.lanes) > 1:
                        deeper = [*deeper, {"id": layout.lane_id(inner), "label": inner.label}]
                    if search(inner, deeper):
                        return True
            return False

        search(self.tree, [])
        return found

    # -- what the canvas is drawn from ----------------------------------------

    def refresh(self, *, status: str = "", error: str = "", keep_overlay: bool = False) -> None:
        """Rebuild every node, edge and pane from the document as it now is.

        The overlay is dropped unless the caller kept it, because it is keyed by
        span and a reparse moves spans. A trace left lying over a canvas that
        has since been edited names the wrong step on every badge, which is a
        failure the other variants shipped and a reader has no way to detect.
        """
        self._rebuilding = True
        try:
            self._rebuild(status=status, error=error, keep_overlay=keep_overlay)
        finally:
            self._rebuilding = False

    def _rebuild(self, *, status: str, error: str, keep_overlay: bool) -> None:
        """Do the rebuilding :meth:`refresh` guards."""
        model, scope = self._stack[-1]
        self.tree = tree.build(model, scope)
        # Read once per rebuild, and before the views are built: every typed
        # field in every node asks it what the class declared.
        self._declared = tree.declarations(model.document)
        self._blocks = {block.id: block for block in tree.walk(self.tree)}
        self._owner = {}
        for lane in tree.lanes_of(self.tree):
            for block in lane.blocks:
                self._owner[block.id] = tree.path_id(lane.path)

        if not keep_overlay:
            self.overlay = {}
        wiring = layout.edges_for(self.tree, model.flow(scope)["edges"])
        # Before the nodes are built, not after: a lane's view says which kind
        # of edge enters it, and it is built during the placement below.
        self.lane_kinds = wiring.entered
        self.enclosed = wiring.enclosed
        views = _Views(self)
        nodes, boxes, _ = layout.place(self.tree, views, wiring.escaping)
        self.boxes = boxes
        self._views = views.made
        # A selection is a document path and an edit renumbers paths, so what
        # was selected before a delete may not be a node at all now. Dropped
        # rather than carried, because a ring on a path that has moved is a ring
        # around whatever took its place.
        if self._select not in self._views:
            self._select = ""
        edges, self.legs = layout.route(wiring.edges, boxes)

        self.flow.param.update(
            nodes=[self._paint(node) for node in nodes],
            edges=edges,
        )
        self.source_pane.param.update(
            source=model.source,
            problems=[],
            marks=self._marks(),
            hints=self._hints(),
        )
        self.reformats = model.reformats()
        if not self.reformats:
            self.rewritten = ""
        self.status = status
        self.error = error
        self._undo.disabled = not self._history
        self._draw_trail(self._select)
        self._paint_status()

    def _paint(self, node: dict[str, Any]) -> dict[str, Any]:
        """Give a placed node its colours."""
        node["style"] = {**node["style"], **_STYLE.get(node["type"], {})}
        return node

    def _marks(self) -> list[dict[str, Any]]:
        """Return what the last run observed, by source line, for the pane.

        The same overlay the blocks wear, joined on the same spans, so the two
        halves of the screen cannot disagree about which statement ran. Empty
        whenever the overlay is, which is after every edit.
        """
        found = []
        for block in self._blocks.values():
            badge, _state = self.badge(block)
            if not badge or not block.span:
                continue
            found.append({
                "line": block.span[0],
                "text": badge,
                "detail": f"`{block.label}` {badge}",
            })
        return found

    def _hints(self) -> dict[str, str]:
        """Return what this package knows about each name, for the pane's hover.

        Not a type: ty says what a name is inferred to be and says it better.
        This says what the resolver made of it, which is the question AWL exists
        to answer and which no type checker is asked.
        """
        found: dict[str, str] = {}
        for binding in self.model.names["bindings"]:
            name = binding.get("local_name")
            identity = binding.get("identity") or {}
            if not name or not identity.get("iri"):
                continue
            where = identity.get("module") or self.model.module
            found[str(name)] = f"`{name}` resolves to `{where}.{identity.get('symbol')}`"
        for owner, fields in self._declared.items():
            for field, declared in fields.items():
                found.setdefault(field, f"`{field}` is declared `{declared}` by `{owner}`")
        return found

    def _problem(self, answer: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the parse failure as a marker for the pane.

        Underlined where it happened rather than only written in the notice
        bar. The pane already carries ty's complaints about a file that parses;
        this is the one complaint that decides whether the canvas moves at all.
        """
        return [
            {
                "line": int(answer.get("line") or 1),
                "column": int(answer.get("offset") or 1),
                "message": f"awl cannot parse this: {answer.get('error')}",
            }
        ]

    def _draw_trail(self, selected: str = "") -> None:
        """Levels, then the containers you are standing in.

        The levels alone said ``awl.ui.sample > procedure`` from inside a branch
        two containers deep, which is true and useless: it names the function
        and not the place. The containers come from the tree, which already
        holds the nesting, so this costs no round trip.
        """
        entries = self.trail
        nested = self.nesting(selected) if selected else []
        items: list[Any] = []
        for index, entry in enumerate(entries):
            if index:
                items.append(_separator())
            here = index == len(entries) - 1 and not nested
            button = _crumb(entry["label"], ["awl-crumb", *(["awl-crumb-here"] if here else [])])
            button.on_click(lambda _event, at=index: self.command({"op": "open", "index": at}))
            items.append(button)
        for index, entry in enumerate(nested):
            items.append(_separator())
            here = index == len(nested) - 1
            button = _crumb(entry["label"], ["awl-crumb", "awl-crumb-in", *(["awl-crumb-here"] if here else [])])
            button.on_click(lambda _event, at=entry["id"]: self.command({"op": "reveal", "path": at}))
            items.append(button)
        self._trail.objects = items

    def _paint_status(self) -> None:
        """Draw the notice, and say what the last write-back cost the file.

        ``reformats`` was computed on every structural edit and shown nowhere,
        so one insert silently took nine blank lines out of the module while the
        notice said only "added". A value edit patches a span and everything
        survives; a structural edit regenerates the module, and the reader has
        to be told what that took before saving.

        What it took is **counted on the file**, before and after, rather than
        written out here as a standing claim. A warning that names something the
        reader can see survive is a warning that stops being read, and this one
        cannot: if a comment ever does survive, the count says so.
        """
        text = self.error or self.status or ""
        css = "awl-status awl-status-bad" if self.error else "awl-status"
        notice = f'<span class="{css}" data-testid="status">{html.escape(text)}</span>'
        if self.reformats and not self.error:
            notice += (
                f'<span class="awl-status awl-status-warn" data-testid="reformats">{html.escape(self.rewritten)}</span>'
            )
        self._status.object = notice

    def say(self, kind: str, text: str) -> None:
        """Write one line into the console.

        Parameters
        ----------
        kind : str
            ``ran``, ``out``, ``step`` or ``error``, which is how it is drawn.
        text : str
            The line.
        """
        self._said.append({"kind": kind, "text": text})
        del self._said[: -self.SAID]
        self.console.lines = list(self._said)

    def _selected(self, event: Any) -> None:
        """Follow the canvas's own selection into the nesting stack.

        Kept alongside the click a block reports for itself, because this one
        also fires when the canvas *clears* a selection, which nothing on a
        block can report.
        """
        if self._rebuilding:
            return
        chosen = (event.new or {}).get("nodes") or []
        self._highlight(chosen[0] if chosen else "")

    def _highlight(self, node_id: str) -> None:
        """Draw one block as the selected one, and take the ring off the rest.

        Through the views rather than through the canvas. The library keeps its
        idea of the selection in the browser and, for any node id it already
        has, overwrites what the editor sent: a ring put there from Python
        showed only on a node that had just been created, which is the one case
        it was needed for and the one case it appeared to work in.
        """
        self._select = node_id
        for path, view in self._views.items():
            view.selected = path == node_id
        self._draw_trail(node_id)
        block = self._blocks.get(node_id)
        if block and block.span:
            self.source_pane.goto = block.span[0]

    # -- what the canvas asks for ---------------------------------------------

    #: Gestures that change the file, and so are worth a snapshot first. A
    #: navigation is not one: going up a level and coming back is not an edit,
    #: and an undo that took those back would need several presses before it
    #: reached anything a reader had actually changed.
    _EDITS = frozenset({"edit", "note", "set_value", "delete", "insert", "move", "source"})

    def command(self, request: dict[str, Any]) -> None:
        """Run one gesture from the canvas, the toolbox or the source pane.

        The handler is looked up before the guard goes on, and called outside
        it. With the lookup and the call under one ``except AttributeError``,
        every ``AttributeError`` raised anywhere inside a handler was reported
        as ``unknown gesture 'move'``, which sends whoever reads it looking for
        a gesture that is wired up perfectly well.
        """
        operation = request.get("op")
        if not operation:
            return
        handler = getattr(self, f"_do_{operation}", None)
        if handler is None:
            self.error = f"unknown gesture {operation!r}"
            self.status = ""
            self._paint_status()
            return
        if operation in self._EDITS:
            self._remember()
        try:
            handler(request)
        except Exception as failure:
            self.error = f"{type(failure).__name__}: {failure}"
            self.status = ""
            self._paint_status()
        finally:
            self._forget_if_unchanged()
        # After the handler, and for a refusal as well as for a crash: a
        # refusal reaches `self.error` without raising, and the notice it lands
        # in is one line that the next gesture overwrites.
        if self.error:
            self.say("error", self.error)

    def _remember(self) -> None:
        """Keep the text an edit is about to replace, with the model holding it."""
        model = self.model
        self._history.append((model, model.source))
        del self._history[: -self.HISTORY]

    def _forget_if_unchanged(self) -> None:
        """Drop the snapshot when the edit it was taken for did nothing.

        A source edit that does not parse, a drop the model refused, a field
        committed to the value it already had: each is a gesture and none of
        them is an edit. Keeping a snapshot for one makes the undo button do
        nothing the first time it is pressed.
        """
        if self._history and self._history[-1][0].source == self._history[-1][1]:
            self._history.pop()
        self._undo.disabled = not self._history

    def _show_level(self) -> None:
        """Put the new level's first block where it can be seen.

        React Flow fits the view once, when it mounts, and a level change
        replaces every node without moving the viewport: descend from a level
        the reader has panned around and the next one is drawn somewhere off the
        left of the canvas. The zoom is left alone, because it is the reader's;
        only the corner is brought back.
        """
        self.flow.viewport = {"x": 40, "y": 24, "zoom": (self.flow.viewport or {}).get("zoom", 0.7)}

    def _do_split(self, request: dict[str, Any]) -> None:
        """Take the source pane's width from the grip between the two halves."""
        low, high = self.SPLIT
        self._pane.width = max(low, min(high, int(request.get("width", self._pane.width))))

    def _do_open(self, request: dict[str, Any]) -> None:
        """Go back to an ancestor level."""
        self._stack = self._stack[: int(request.get("index", 0)) + 1]
        self.refresh(status=f"opened {self.scope or 'module'}")
        self._show_level()

    def _do_reveal(self, request: dict[str, Any]) -> None:
        """Select the container a nesting crumb names."""
        self._highlight(str(request["path"]))

    def _do_select(self, request: dict[str, Any]) -> None:
        """Take a selection from the block that was clicked."""
        self._highlight(str(request["path"]))

    def _do_descend(self, request: dict[str, Any]) -> None:
        """Open the level a block stands for.

        A declaration and a call are the same gesture and the same result: a
        level is a scope, and descending produces another scope. Nothing counts
        depth, so nothing limits it.
        """
        block = self._blocks[str(request["path"])]
        if not block.opens:
            self.error = "this block does not open into a level"
            self._paint_status()
            return
        into = self.model
        if block.opens_module:
            step = next((s for s in self.model.plan["steps"] if s["id"] == block.plan), None)
            into = (self.model.descend(step) if step else None) or self.model
        self._stack.append((into, block.opens))
        self.refresh(status=f"opened {block.opens}")
        self._show_level()

    def _do_edit(self, request: dict[str, Any]) -> None:
        """Rewrite the source a block covers, or the condition it tests.

        The escape hatch every block shares. A loop's test, a return expression,
        a bare assignment: there is no form for an arbitrary expression that is
        not a Python editor with extra steps, so the block is edited through the
        text it stands for.
        """
        block = self._blocks[str(request["path"])]
        span = block.condition_span if block.lanes and block.condition_span else block.span
        if span is None:
            self.error = "this block covers no source"
            self._paint_status()
            return
        answer = self.model.replace_at(list(span), str(request["text"]))
        if not answer.get("ok"):
            self.refresh(error=f"line {answer.get('line')}: {answer.get('error')}")
            return
        self.refresh(status="edited")

    def _do_note(self, request: dict[str, Any]) -> None:
        """Rewrite the comment a block carries, or write its first one.

        Through the model, which reads and writes a note by span and nothing
        else. ``to_source`` regenerates the whole module the moment a structural
        patch is pending, and regenerating drops every comment in the file: a
        note written that way would delete itself and everything like it.

        The rules are :meth:`~awl.ui.EditorModel.set_trivia`'s, not this
        canvas's. This module had a copy of them and the copy was wrong about a
        statement whose first line ends inside a string: a note written on a
        docstring went into the literal and changed what it said.
        """
        block = self._blocks[str(request["path"])]
        if block.note_span is None or block.span is None:
            self.error = "this block has nowhere to keep a note"
            self._paint_status()
            return
        text = str(request["text"])
        answer = self.model.set_trivia(list(block.span), text)
        if not answer.get("ok"):
            self.refresh(error=f"line {answer.get('line')}: {answer.get('error')}")
            return
        self.refresh(status="noted" if text.strip().lstrip("#").strip() else "note removed")

    def _do_set_value(self, request: dict[str, Any]) -> None:
        """Set one value through a field inside the node, written back by span.

        A float field whose widget hands back an int would be written as ``4``
        and quietly change the field's type, so the value already there says
        which it should be.
        """
        path = list(request["path"])
        value = request["value"]
        previous = self._value(path)
        if isinstance(previous, float) and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if previous == value and type(previous) is type(value):
            return
        self.model.set_value(path, value)
        model = self.model
        answer = model.set_source(model.to_source())
        if not answer.get("ok"):
            self.refresh(error=str(answer.get("error")))
            return
        self.refresh(status="edited")

    def _do_delete(self, request: dict[str, Any]) -> None:
        """Remove a block, wherever it sits."""
        path = tree.path_of(str(request["path"]))
        self.model.apply("delete_step", path=path)
        self._fill(path[:-1])
        self._rebase("deleted")

    def _do_insert(self, request: dict[str, Any]) -> None:
        """Add a block to a statement list, at the position it was dropped.

        ``add_step`` appends, so a drop in the middle is an append and a move.
        Two operations rather than a third one grown here: the editing semantics
        are :mod:`awl.editor`'s, and a variant that grew its own would be
        measuring its own reimplementation.
        """
        into = tree.path_of(str(request["into"]))
        node = self._template(str(request.get("kind", "")))
        # Asked of the list the drop *would* make, before anything is applied.
        # Appending first and deleting again on a refusal left the model with
        # two structural patches that cancel out, and `to_source` cannot see
        # that they do: the next value edit anywhere in the file would have
        # regenerated the whole module and dropped its comments.
        steps = self._steps(into)
        last = len(steps)
        index = min(int(request.get("index", last)), last)
        if index < last:
            refusal = tree.movable([*steps, node], last, index)
            if refusal:
                self.refresh(error=refusal)
                return
        self.model.apply("add_step", into=into, node=node)
        if index < last:
            self.model.apply("reorder", path=into, frm=last, to=index)
        self._rebase("added", select=tree.path_id([*into, index]))

    def _do_move(self, request: dict[str, Any]) -> None:
        """Move a block, including into and out of a container.

        This is what makes what a loop encloses editable rather than decorative.
        Within one list it is a reorder. Across two it is a delete and an insert,
        and the insert path has to be corrected for the delete, or it lands in a
        list that has already been renumbered.
        """
        source = tree.path_of(str(request["path"]))
        into = tree.path_of(str(request["into"]))
        index = int(request["index"])

        if source[:-1] == into:
            if index > source[-1]:
                index -= 1
            refusal = tree.movable(self._steps(into), source[-1], index)
            if refusal:
                self.refresh(error=refusal)
                return
            self.model.apply("reorder", path=into, frm=source[-1], to=index)
            self._rebase("moved", select=tree.path_id([*into, index]))
            return

        refusal = self._crossing(source, into, index)
        if refusal:
            self.refresh(error=refusal)
            return

        node = copy.deepcopy(self._at(source))
        self.model.apply("delete_step", path=source)
        self._fill(source[:-1])
        into = _shift(into, source)
        self.model.apply("add_step", into=into, node=node)
        length = len(self._steps(into))
        index = min(index, length - 1)
        if index < length - 1:
            self.model.apply("reorder", path=into, frm=length - 1, to=index)
        self._rebase("moved", select=tree.path_id([*into, index]))

    def _crossing(self, source: list[Any], into: list[Any], index: int) -> str:
        """Return why carrying a block into another list is refused, or ``""``.

        Two questions, and both have to be asked. What is being carried: taking
        a class out of the module and dropping it into a loop body is not a
        reordering of the flow either. And where it would land: arriving in the
        module above its import is the same edit as being dragged there within
        it, and a check that asked only about the block would have let the
        second in through the first's door.
        """
        node = self._at(source)
        if not isinstance(node, dict):
            return "that is not a statement"
        kind = node.get("@type")
        if kind is None:
            return "a docstring belongs to what declares it"
        if kind in tree.DECLARATIONS:
            return f"{tree.names_of(node)} is a declaration, and moving it is not moving the flow"
        steps = self._steps(into)
        return tree.movable([*steps, node], len(steps), min(index, len(steps)))

    def _do_source(self, request: dict[str, Any]) -> None:
        """Take an edit from the source pane.

        A half-typed edit is the normal state of a source pane, and one that
        does not parse changes nothing at all: a canvas rebuilt from a partial
        tree would flicker through files that never existed.
        """
        answer = self.model.set_source(str(request["text"]))
        if not answer.get("ok"):
            self.error = f"line {answer.get('line')}: {answer.get('error')}"
            self.status = ""
            self._paint_status()
            # Straight to the pane, because a failed parse deliberately skips
            # the rebuild: the canvas must not flicker through a file that never
            # existed, and the reader must still be shown where it broke.
            self.source_pane.problems = self._problem(answer)
            return
        self._reopen()
        self.refresh(status="source applied")

    def _do_undo(self, _request: dict[str, Any]) -> None:
        """Put the file back the way it was before the last edit.

        Through the model, which is the only way an undo can be honest here: the
        canvas is drawn from the document and every node on it is identified by
        its path in that document, so an undo the file does not know about
        leaves a canvas whose every id names a statement that has moved.
        """
        if not self._history:
            self.refresh(status="nothing to undo")
            return
        model, text = self._history.pop()
        answer = model.set_source(text)
        if not answer.get("ok"):
            self.refresh(error=str(answer.get("error")))
            return
        self._reopen()
        self.refresh(status="undone")

    def _do_run(self, request: dict[str, Any]) -> None:
        """Run the procedure, lay what happened over the canvas, and say what it said.

        The run and the drawing are two different levels. ``entry`` is what was
        called; the canvas shows whatever level the reader is standing on, and
        the trace may have gone nowhere near it. Both are named in the status,
        because a message reading ``ran procedure: 4/5`` while ``charge`` is on
        screen attributes one level's numbers to another level's name.

        Whatever the procedure prints goes to the console. Nothing captured it
        before, so a ``print`` in a step being debugged went to the terminal the
        server was started from, which a reader of the page does not have.
        """
        entry = request.get("entry") or self._entry
        arguments = tuple(request.get("arguments", self._arguments))
        if not entry:
            self.refresh(error="no entry point configured")
            return

        self.say("ran", f"{entry}({', '.join(repr(value) for value in arguments)})")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            result = self.model.run(entry, *arguments)
        for line in printed.getvalue().splitlines():
            self.say("out", line)
        if not result.get("overlay"):
            self.refresh(error=str(result.get("error") or "the run produced nothing"))
            return

        by_span = {}
        for record in result["overlay"]["executions"]:
            key = tree.span_key(record.get("span"))
            if key:
                by_span[key] = record

        drawn: dict[str, dict[str, Any]] = {}
        for block in self._blocks.values():
            record = by_span.get(tree.span_key(block.span) or (0, 0, 0, 0))
            if record is None:
                continue
            drawn[block.id] = {
                "executed": bool(record.get("executed")),
                "iterations": len(record.get("iterations") or []),
                "branch_taken": record.get("branch_taken") or [],
                "events": record.get("event_count", 0),
            }

        here = self.scope or self.model.module or "module"
        # A level the trace never reached is not a level that did not run. The
        # module's own statements execute before the tracer is installed, so
        # standing on the module and pressing run greyed out every block and
        # reported 0/2, which says the file did nothing. Nothing was observed;
        # that is a different sentence and it is the true one.
        ran = sum(1 for record in drawn.values() if record["executed"])
        seen = any(record["executed"] or record["events"] for record in drawn.values())
        self.overlay = drawn if seen else {}
        said = (
            f"ran {entry}: {ran}/{len(drawn)} steps in {here} executed"
            if seen
            else f"ran {entry}: nothing in {here} was traced"
        )
        self.refresh(status=said, error=str(result.get("error") or ""), keep_overlay=True)
        self.say("out", said)
        # What the trace reported, per step, which is the half that never fitted
        # in a one-line notice: the badges on the canvas say it a block at a
        # time and nothing said it as a list.
        for block in tree.walk(self.tree):
            badge, _state = self.badge(block)
            if badge:
                self.say("step", f"{block.label}  {badge}")

    # -- helpers --------------------------------------------------------------

    def badge(self, block: tree.Block) -> tuple[str, str]:
        """Return what a block's node says about the last run, and its state.

        The count first, then which way the test went, and a bare ``ran`` or
        ``not run`` for a statement that has neither. The count is written with
        a multiplication sign, because three times round a loop is a count and
        not a name.
        """
        record = self.overlay.get(block.id)
        if record is None:
            return "", ""
        parts = []
        if record["iterations"] > 0:
            parts.append(f"×{record['iterations']}")  # noqa: RUF001 - a count, not a name
        taken = record["branch_taken"]
        if taken:
            parts.append("T+F" if True in taken and False in taken else "T" if True in taken else "F")
        if not parts:
            parts.append("ran" if record["executed"] else "not run")
        return " ".join(parts), "ran" if record["executed"] else "skipped"

    def _rebase(self, what: str, *, select: str = "") -> None:
        """Write a structural edit back and reparse from the result.

        A structural patch is not a range of characters, so the whole module is
        regenerated and the file loses whatever regenerating loses. What that
        was is measured here, on the two texts, and reported as a count rather
        than as a claim made in advance. Reparsing immediately is what keeps
        every span, path and step identity on the canvas addressing the file
        that now exists.
        """
        model = self.model
        # Asked before the write, not after: `to_source` regenerates when a
        # structural patch is pending, and the reparse that follows leaves
        # nothing to report.
        reformatted = model.reformats()
        before = model.source
        answer = model.set_source(model.to_source())
        if not answer.get("ok"):
            self.refresh(error=str(answer.get("error")))
            return
        lost = _lost(before, model.source) if reformatted else ""
        self._reopen()
        # Before the rebuild, because the nodes carry their own selection and
        # they are built inside `refresh`. Set afterwards it took a second
        # rebuild to show, which is how an insert came to report "added" with
        # nothing on the canvas saying which block had appeared.
        if select:
            self._select = select
        self.refresh(status=what)
        # After `refresh`, which reads both from a model that has just been
        # reparsed and so reports nothing pending. Repainted because the notice
        # is drawn from them and was drawn before this line ran.
        self.reformats = reformatted
        self.rewritten = lost
        self._paint_status()

    def _reopen(self) -> None:
        """Drop any level below one whose function no longer exists."""
        kept = [self._stack[0]]
        for held, name in self._stack[1:]:
            try:
                tree.find_scope(held.document, name)
            except LookupError:
                break
            kept.append((held, name))
        self._stack = kept

    def _fill(self, holder: list[Any]) -> None:
        """Put a ``pass`` in a statement list an edit has just emptied.

        Taking the only statement out of a branch is a legitimate edit and the
        result is not Python: a suite has to hold something. Refusing the delete
        instead would make the last block in every branch the one block that
        cannot be removed.

        An ``else`` is exempt, because an ``if`` with an empty one is an ``if``.
        Filling it would write ``else: pass`` into the file for a reader who
        only emptied a lane, and leave a statement nobody asked for behind.
        """
        if holder and holder[-1] in tree.OPTIONAL_SLOTS:
            return
        if not isinstance(self._at(holder), list) or self._at(holder):
            return
        self.model.apply("add_step", into=holder, node={"@type": "Pass"})

    def _template(self, kind: str) -> dict[str, Any]:
        """Return the compact node a dropped toolbox entry stands for."""
        for _name, items in TOOLBOX:
            for entry_kind, _label, code in items:
                if entry_kind == kind:
                    return pipeline.to_compact(code, module="", file="<toolbox>", spans=False)["body"][0]
        raise LookupError(f"nothing in the toolbox called {kind!r}")

    def declared(self, owner: str, name: str) -> str:
        """Return the type *owner* declares for its *name* field, or ``""``.

        Empty for a plain literal, which belongs to no class and so has nothing
        to declare it.
        """
        if not owner or not name:
            return ""
        return self._declared.get(owner, {}).get(name, "")

    def _at(self, path: list[Any]) -> Any:
        node: Any = self.model.document
        for part in path:
            node = node[part]
        return node

    def _steps(self, path: list[Any]) -> list[Any]:
        """Return the statements in the list at *path*, empty where it is absent.

        A statement list that holds nothing is not in the document:
        :func:`awl.compact.encode` drops an empty required list, so an ``if``
        with no ``else`` carries no ``orelse`` key. Reading one raised
        ``KeyError: 'orelse'`` on the first block dropped into an empty branch,
        which is the one lane on this canvas that can be empty.
        """
        try:
            found = self._at(path)
        except (KeyError, IndexError, TypeError):
            return []
        return found if isinstance(found, list) else []

    def _value(self, path: list[Any]) -> Any:
        try:
            found = self._at(path)
        except (KeyError, IndexError, TypeError):
            return None
        return found.get("literal") if isinstance(found, dict) else found

    # -- the page --------------------------------------------------------------

    def __panel__(self) -> Any:
        """Return the whole editor: bar, toolbox, canvas, source, console."""
        bar = pn.Row(
            self._trail,
            pn.HSpacer(),
            self._undo,
            self._run,
            self._status,
            sizing_mode="stretch_width",
            height=38,
            margin=0,
            css_classes=["awl-bar"],
            stylesheets=[_SHELL_CSS],
        )
        side = pn.Column(
            pn.pane.HTML("Toolbox", css_classes=["awl-pane-head"], margin=(6, 8), sizing_mode="stretch_width"),
            self.toolbox,
            width=168,
            margin=0,
            css_classes=["awl-side"],
            stylesheets=[_SHELL_CSS],
            sizing_mode="stretch_height",
        )
        bottom = pn.Column(
            pn.pane.HTML("console", css_classes=["awl-pane-head"], margin=(4, 10), sizing_mode="stretch_width"),
            self.console,
            height=self._console_height,
            margin=0,
            css_classes=["awl-bottom"],
            stylesheets=[_SHELL_CSS],
            sizing_mode="stretch_width",
        )
        return pn.Column(
            bar,
            pn.Row(side, self.flow, self.splitter, self._pane, sizing_mode="stretch_both", margin=0),
            bottom,
            sizing_mode="stretch_both",
            margin=0,
            stylesheets=[_SHELL_CSS],
        )


class _Views:
    """Builds the Panel object that lives inside each node.

    This is the whole point of the variant, so it is worth saying what is and is
    not custom. The typed fields are :class:`panel.widgets.FloatInput`,
    :class:`panel.widgets.IntInput`, :class:`panel.widgets.TextInput` and
    :class:`panel.widgets.Checkbox`: ordinary Panel widgets, in a
    :class:`panel.Row`, inside the node. Only the header line is custom, because
    a gesture is not a value: a double-click and a drag have no widget.
    """

    def __init__(self, editor: PanelReactFlowEditor) -> None:
        self.editor = editor
        #: Every view built this pass, by node id, so the selection can be moved
        #: afterwards without rebuilding the level to move it.
        self.made: dict[str, Any] = {}

    def block(self, block: tree.Block) -> Any:
        badge, state = self.editor.badge(block)
        editable = block.role != "level"
        text = (block.condition if block.lanes else block.text) if editable else block.label
        head = components.BlockView(
            kind=_chip(block),
            text=text,
            path=block.id,
            role=block.role,
            opens=block.opens,
            calls=block.calls,
            resolved=block.resolved,
            badge=badge,
            state=state,
            note=block.note,
            note_where=block.note_where,
            notable=block.notable,
            multiline="\n" in text,
            editable=editable,
            selected=block.id == self.editor.selected,
            on_command=self.editor.command,
            height=layout.GEOMETRY["block_height"] + (layout.GEOMETRY["note_height"] if block.notable else 0),
            sizing_mode="stretch_width",
            margin=0,
        )
        self.made[block.id] = head
        if not block.fields:
            return head
        return pn.Column(head, self.fields(block), margin=0, sizing_mode="stretch_width")

    def fields(self, block: tree.Block) -> Any:
        """Return the node's own form: one Panel widget per settable value.

        Laid out with the same inset the block's own header uses, and stretched
        rather than pinned to a width computed from a constant. Two fields sized
        against ``block_width`` while the node had grown to its lane's width sat
        three pixels left of the header above them and the second one ran off
        the node's right edge, which is a hard thing to notice and the exact
        thing this variant argues it does better than a side panel.
        """
        widgets = [self._field(entry) for entry in block.fields]
        return pn.Row(
            *widgets,
            height=layout.GEOMETRY["fields_height"],
            margin=0,
            sizing_mode="stretch_width",
            css_classes=["awl-fields"],
            stylesheets=[_FIELDS_CSS],
        )

    def _field(self, entry: dict[str, Any]) -> Any:
        value = entry["value"]
        shared = {
            "label": entry["label"],
            "margin": 0,
            "sizing_mode": "stretch_width",
            "css_classes": ["awl-field"],
            "stylesheets": [_FIELD_CSS],
        }
        # The declaration first, and the value only when there is no
        # declaration to read. `target_voltage=4` is a `float` field holding an
        # integer literal, and inferring from the literal rendered a spinner
        # that stepped in ones and could not express 4.35 at all.
        declared = self.editor.declared(entry.get("owner", ""), entry.get("name", ""))
        if declared == "bool" or (not declared and isinstance(value, bool)):
            widget = pn.widgets.Checkbox(value=bool(value), **shared)
        elif declared == "int" or (not declared and isinstance(value, int)):
            widget = pn.widgets.IntInput(value=int(value or 0), **shared)
        elif declared == "float" or (not declared and isinstance(value, float)):
            widget = pn.widgets.FloatInput(value=float(value or 0), step=0.05, **shared)
        else:
            widget = pn.widgets.TextInput(value="" if value is None else str(value), **shared)
        widget.param.watch(
            lambda event, at=entry["path"]: self.editor.command({"op": "set_value", "path": at, "value": event.new}),
            "value",
        )
        return widget

    def lane(self, lane: tree.Lane) -> Any:
        view = components.LaneView(
            label=lane.label,
            kind=self.editor.lane_kinds.get(layout.lane_id(lane), lane.label),
            selected=layout.lane_id(lane) == self.editor.selected,
            height=layout.GEOMETRY["lane_head"],
            sizing_mode="stretch_width",
            margin=0,
        )
        self.made[layout.lane_id(lane)] = view
        return view

    def zone(self, lane: tree.Lane, index: int) -> Any:
        return components.DropZone(
            lane=tree.path_id(lane.path),
            index=index,
            on_command=self.editor.command,
            height=layout.GEOMETRY["zone_height"],
            sizing_mode="stretch_width",
            margin=0,
        )


#: The row the typed fields sit in, inset exactly as the header above it.
#:
#: ``--awl-inset`` is the block's own, repeated here because the two live in
#: different shadow roots and a custom property does not cross a Panel component
#: boundary: this is the one place the number appears twice, and a test measures
#: both against the node's rectangle rather than trusting it.
_FIELDS_CSS = """
:host(.awl-fields) {
  display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
  align-items: center; gap: 8px; padding: 0 9px; box-sizing: border-box;
}
"""

#: A field inside a node is a form control at the size a node can carry: the
#: label above it in nine pixels, the input under it, and no card around either.
_FIELD_CSS = """
:host {
  --design-primary-color: #4338ca;
  flex: 1 1 0 !important; min-width: 0 !important; width: auto !important;
}
label, .bk-input-group label {
  font: 600 9px/1.2 ui-sans-serif, system-ui !important; color: #475569 !important;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block;
}
input, .bk-input {
  font: 12px ui-monospace, monospace !important; padding: 2px 6px !important;
  height: 24px !important; width: 100% !important; box-sizing: border-box !important;
}
"""


def _crumb(label: str, classes: list[str]) -> Any:
    """Return one level of the path bar, carrying the rules that style it."""
    return pn.widgets.Button(
        label=label, color="light", height=24, margin=(4, 0), css_classes=classes, stylesheets=[_CRUMB_CSS]
    )


def _separator() -> Any:
    """Return the mark between two crumbs."""
    return pn.pane.HTML("&rsaquo;", margin=(6, 0), css_classes=["awl-sep"], stylesheets=[_SEPARATOR_CSS])


def _no_editor(_data: Any, _schema: Any, **_options: Any) -> None:
    """Decline the library's own editor. The node's ``view`` is the form."""
    return None


def _chip(block: tree.Block) -> str:
    """Return the word a block wears, which is its Python node type."""
    if block.role == "level":
        return "level"
    return block.kind


def _lost(before: str, after: str) -> str:
    """Return what rewriting the module whole took out of it, counted on the file.

    Parameters
    ----------
    before, after : str
        The module either side of the write-back.

    Returns
    -------
    str
        What the warning says, or a sentence saying there was nothing to lose.

    Notes
    -----
    Counted rather than declared. The notice used to read "comments and blank
    lines not preserved" whatever had happened, which is a claim about every
    rewrite and is therefore wrong about the ones that cost nothing: a reader
    who watches a warning fire over a file with no comment in it stops reading
    the warning, and the next one is about their comment.
    """
    from awl import writeback

    gone = len(writeback.comments(before)) - len(writeback.comments(after))
    blanks = _blank(before) - _blank(after)
    parts = []
    if gone > 0:
        parts.append(f"{gone} comment{'s' if gone > 1 else ''}")
    if blanks > 0:
        parts.append(f"{blanks} blank line{'s' if blanks > 1 else ''}")
    return f"rewritten: {' and '.join(parts)} gone" if parts else "rewritten: nothing was lost"


def _blank(text: str) -> int:
    """Return how many lines of *text* carry nothing."""
    return sum(1 for line in text.splitlines() if not line.strip())


def _shift(target: list[Any], removed: list[Any]) -> list[Any]:
    """Return *target* corrected for a statement having been removed.

    Every path into the list that held the removed statement, at a position
    after it, is now one lower. Moving a block out of a loop is a delete and an
    insert, and without this the insert lands in the list the delete renumbered.
    """
    holder, index = removed[:-1], removed[-1]
    if not isinstance(index, int) or target[: len(holder)] != holder or len(target) <= len(holder):
        return target
    at = target[len(holder)]
    if isinstance(at, int) and at > index:
        return [*holder, at - 1, *target[len(holder) + 1 :]]
    return target


def open_sample(scope: str = "procedure", **options: Any) -> PanelReactFlowEditor:
    """Return the editor over the procedure every variant opens on."""
    options.setdefault("ty_url", f"/{TY_ROUTE}/ty_wasm.js" if ty_assets() else "")
    return PanelReactFlowEditor(ui.open_sample(), scope=scope, entry="procedure", arguments=(3,), **options)


def serve(port: int = 8104, *, show: bool = False, **options: Any) -> Any:
    """Serve the editor on a fixed port.

    Panel is a hard dependency here in a way it is not for the other four, and
    this is where that shows: an anywidget renders in whatever host already has
    a kernel, and this needs a server of its own.

    The type checker is mounted as static files rather than fetched from a CDN,
    because the npm package called ``ty_wasm`` is version 0.0.0 and is not
    Astral's. A static build points the pane at the same path under its own
    origin.
    """
    pn.extension()
    assets = ty_assets()
    if assets is not None:
        options.setdefault("static_dirs", {}).setdefault(TY_ROUTE, str(assets))
    return pn.serve(
        {"/": lambda: open_sample().__panel__()},
        port=port,
        address="127.0.0.1",
        show=show,
        websocket_origin=[f"127.0.0.1:{port}", f"localhost:{port}"],
        **options,
    )
