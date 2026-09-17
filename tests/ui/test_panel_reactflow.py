"""The fifth canvas, in a real browser.

Every shot is taken inside the test that asserts the state it is named for, so a
screenshot cannot drift from what the editor does: if the assertion stops
holding there is no image, and if the image is wrong the assertion above it was
wrong first. The last test in the file hashes all ten and refuses duplicates,
because two identical files with different names is the failure that is easiest
to ship and hardest to notice.

The editor is **served**, by Panel, on the loopback. That is not a testing
convenience: this variant is a Panel application and cannot be rendered any
other way, which is the cost of the choice and is measured rather than argued
about in ``test_what_the_page_costs_over_the_wire``.

It **clicks and types**. ``locator.fill()`` sets a value without ever placing a
caret, and where the caret goes is exactly what has been broken in this
comparison before: a source pane two thirds of which could not be clicked into
passed every test written with ``fill()``.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("panel_reactflow")

import panel as pn

from awl import ui
from awl.ui import panel_reactflow as prf
from awl.ui.panel_reactflow import components, layout, tree

SHOTS = Path(__file__).resolve().parents[2] / "docs" / "assets" / "ui" / "panel_reactflow"
VIEWPORT = {"width": 1280, "height": 800}

#: The names every shot in this variant is required to carry.
NAMED = (
    "01-level",
    "02-form",
    "03-edited",
    "04-descended",
    "05-trace",
    "06-nesting",
    "08-added",
    "09-sublevel",
    "10-run",
    "11-source-edit",
)

#: The shots the named ten do not cover.
#:
#: "07-dropping", because the drop zone is only visible while a drag is running
#: and "08-added" has to show what was added rather than the gesture that added
#: it. The rest are the states a review found this variant had no picture of,
#: each of which is a claim about what the editor refuses or warns about rather
#: than about what it draws.
EXTRA = (
    "07-dropping",
    "12-refused",
    "13-reformats",
    "14-declared",
    "15-resolved",
    "16-selected",
    "17-bounded-run",
    "18-diagnostic",
    "19-hover",
    "20-completion",
    "21-edges",
    "22-fields-aligned",
    "23-note",
    "24-source-overlay",
    # What a person using the editor found wrong with it, one picture each.
    "25-when-false",
    "26-note-above",
    "27-dropped-into-else",
    "28-moved-into-else",
    "29-splitter",
    "30-codicons",
    "31-console",
    "32-lane-label",
    "33-ring",
    "34-join",
    "35-shell",
)

#: Bodies fetched from the CDN once per session and replayed into every page.
#:
#: Monaco is 851 kB and a Playwright page is a fresh browser context, so without
#: this every test in the file pays for it again: the suite spent longer
#: downloading one editor thirty times than running.
_CDN: dict[str, tuple[bytes, dict[str, str], int]] = {}

#: What a replayed response has to keep saying. A font fetched by a stylesheet
#: is a CORS request whatever its origin, so a replay that hands back the bytes
#: and forgets the header fails with ``NetworkError`` and the icons fall back to
#: the notdef box: the cache was hiding the very thing the icon test asserts.
_KEEP = ("content-type", "access-control-allow-origin", "cross-origin-resource-policy")

#: What the badge writes before an iteration count. A multiplication sign, not
#: an x, and named once so the assertions do not each carry a lookalike glyph.
TIMES = "×"  # noqa: RUF001

#: The blocks of the sample the assertions keep coming back to.
CHARGE = "body.7.body.3.body.0"
LOOP = "body.7.body.3"
BRANCH = "body.7.body.3.body.1"
THEN_FIRST = "body.7.body.3.body.1.body.0"
#: The last statement inside the loop, which is where control turns back from.
LAST_IN_LOOP = "body.7.body.3.body.3"
#: The lane that holds the loop's body, and the branch's two.
LOOP_LANE = "lane:body.7.body.3.body"
THEN_LANE = "lane:body.7.body.3.body.1.body"
ELSE_LANE = "lane:body.7.body.3.body.1.orelse"

#: What the other four variants reported for themselves.
#:
#: **Reported by their builders, not derived here.** Each was measured by that
#: variant's own suite on its own branch: nothing in this checkout can recompute
#: them, so nothing here pretends to. They are quoted with that caveat attached,
#: which is the only honest way to quote a number you cannot reproduce, and
#: this variant's own figure is not like-for-like with any of them anyway,
#: because its JavaScript arrives built inside a wheel.
REPORTED = {
    "swd": {"wire": 86_748, "decoded": 275_754, "requests": 6},
    "reactflow_jedison": {"wire": 263_493, "decoded": 684_707, "requests": 19},
    "blockly": {"wire": 450_536, "decoded": 1_745_727, "requests": 9},
    "reactflow_rjsf": {"wire": 766_048, "decoded": 1_620_990, "requests": 269},
}


# -- the server ----------------------------------------------------------------


class _Live:
    """One Panel server, and the editor the page currently open on it is using.

    A fresh editor per page load, because reloading is how anyone starts over
    and a demo whose model outlives the page inherits whatever the last visitor
    did to it.
    """

    def __init__(self) -> None:
        pn.extension()
        self.editor: prf.PanelReactFlowEditor | None = None
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        # Bound to zero and read back, because another instance of this editor
        # may well be running: a hard-coded port makes the suite depend on what
        # else the machine is doing.
        self.ty = prf.ty_assets()
        self.thread = pn.serve(
            {"/": self._app},
            port=self.port,
            address="127.0.0.1",
            show=False,
            threaded=True,
            verbose=False,
            static_dirs={prf.TY_ROUTE: str(self.ty)} if self.ty else {},
            websocket_origin=[f"127.0.0.1:{self.port}", f"localhost:{self.port}"],
        )
        self.url = f"http://127.0.0.1:{self.port}/"
        time.sleep(2)

    def _app(self) -> Any:
        self.editor = prf.open_sample()
        return self.editor.__panel__()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.thread.stop()


@pytest.fixture(scope="module")
def live():
    served = _Live()
    yield served
    served.close()


@pytest.fixture
def shots():
    SHOTS.mkdir(parents=True, exist_ok=True)
    return SHOTS


def cache_the_cdn(page: Any) -> None:
    """Fetch Monaco once per session and replay it into every later page.

    The bytes are the CDN's own, recorded on the first page that asked for them
    and handed back verbatim. ``test_what_the_page_costs_over_the_wire`` does
    not install this, because a measurement taken through a cache measures the
    cache.
    """

    def serve(route: Any) -> None:
        url = route.request.url
        if url in _CDN:
            body, headers, _size = _CDN[url]
            route.fulfill(body=body, headers=headers)
            return
        answer = route.fetch()
        body = answer.body()
        headers = {name: value for name, value in answer.headers.items() if name.lower() in _KEEP}
        headers.setdefault("content-type", "text/javascript")
        _CDN[url] = (body, headers, len(body))
        route.fulfill(response=answer, body=body)

    page.route("https://cdn.jsdelivr.net/**", serve)


def publish_monaco(page: Any) -> None:
    """Ask Monaco to publish its own API, so a test can read what it is holding.

    Monaco does this itself when ``MonacoEnvironment.globalAPI`` is set before
    it loads, and an init script is before everything. Nothing is added to the
    editor for the benefit of its tests: a test hook in the source is a second
    implementation of the thing under test, and this reads the first one.

    It is also the only way to see what the pane holds. Monaco renders the lines
    on screen and no others, so the file is not in the document and an
    assertion on ``text_content`` would be an assertion about the viewport.
    """
    page.add_init_script("window.MonacoEnvironment = { ...(window.MonacoEnvironment || {}), globalAPI: true }")


def open_editor(page: Any, live: _Live, *, cache: bool = True, ty: bool = False) -> prf.PanelReactFlowEditor:
    """Load the page and hand back the editor the server built for it.

    Parameters
    ----------
    cache : bool, optional
        Replay Monaco from the session cache rather than fetching it again.
    ty : bool, optional
        Wait for the type checker as well. Off by default: ty is 17.7 MB of
        WebAssembly and most of these tests are about the canvas, so waiting for
        it everywhere would pay for it everywhere.
    """
    page.set_viewport_size(VIEWPORT)
    publish_monaco(page)
    if cache:
        cache_the_cdn(page)
    page.goto(live.url, wait_until="domcontentloaded")
    page.wait_for_selector(".react-flow__node", timeout=45_000)
    page.wait_for_selector('[data-path="body.7.body.0"]', timeout=45_000)
    page.wait_for_selector(".monaco-editor", timeout=45_000)
    page.wait_for_timeout(1400)
    editor = live.editor
    assert editor is not None
    if ty:
        assert live.ty is not None, "ty_wasm was not found; set AWL_TY_WASM to the directory holding it"
        settle(page, lambda: editor.source_pane.checked >= 0, timeout=120)
        assert editor.source_pane.checked >= 0, "the type checker never started"
    return editor


def caret(page: Any) -> dict[str, int]:
    """Where the caret is in the source pane, as Monaco reports it."""
    return page.evaluate(
        "() => { const at = monaco.editor.getEditors()[0].getPosition();"
        " return { line: at.lineNumber, column: at.column } }"
    )


def source_text(page: Any) -> str:
    """What the source pane holds, read from Monaco rather than from the DOM."""
    return page.evaluate("() => monaco.editor.getEditors()[0].getModel().getValue()")


def markers(page: Any, owner: str) -> list[dict[str, Any]]:
    """The diagnostics Monaco is holding for one owner."""
    return page.evaluate(
        "(owner) => monaco.editor.getModelMarkers({ owner })"
        ".map(m => ({ message: String(m.message), line: m.startLineNumber, column: m.startColumn,"
        " code: String((m.code && m.code.value) || m.code || '') }))",
        owner,
    )


def deep(page: Any, selector: str) -> list[Any]:
    """Every element matching a selector, shadow roots included, as boxes."""
    return page.evaluate(
        """(selector) => {
          const found = []
          const walk = root => {
            for (const el of root.querySelectorAll('*')) {
              if (el.matches(selector)) found.push(el)
              if (el.shadowRoot) walk(el.shadowRoot)
            }
          }
          walk(document)
          return found.map(el => ({
            text: el.textContent,
            className: el.className,
            color: getComputedStyle(el).color,
            font: getComputedStyle(el).fontFamily,
            box: el.getBoundingClientRect().toJSON(),
          }))
        }""",
        selector,
    )


def spot(page: Any, needle: str, offset: int = 1) -> dict[str, float]:
    """Where on screen a word in the source pane is, scrolled to if need be."""
    where = page.evaluate(
        """(args) => {
          const view = monaco.editor.getEditors()[0]
          const text = view.getModel()
          for (let line = 1; line <= text.getLineCount(); line++) {
            const at = text.getLineContent(line).indexOf(args.needle)
            if (at < 0) continue
            view.revealLineInCenter(line)
            const seen = view.getScrolledVisiblePosition({ lineNumber: line, column: at + 1 + args.offset })
            const box = view.getDomNode().getBoundingClientRect()
            return { x: box.left + seen.left + 2, y: box.top + seen.top + seen.height / 2, line: line }
          }
          return null
        }""",
        {"needle": needle, "offset": offset},
    )
    assert where, f"{needle!r} is not in the source pane"
    return where


def hover_source(page: Any, needle: str, offset: int = 1) -> dict[str, float]:
    """Put the pointer on a word in the source pane, the way a reader does."""
    where = spot(page, needle, offset)
    page.wait_for_timeout(200)
    page.mouse.move(where["x"] - 60, where["y"])
    page.wait_for_timeout(150)
    page.mouse.move(where["x"], where["y"])
    return where


def click_source(page: Any, fraction: float) -> None:
    """Click a fraction of the way down the source pane."""
    box = page.locator(".awl-source").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * fraction)


def settle(page: Any, until: Any = None, timeout: float = 12.0) -> None:
    """Wait for the round trip a gesture starts.

    Panel answers over a websocket and then rebuilds every node, so the states
    worth waiting for are on the Python side. Where a test knows which one it is
    waiting for it says so; where it does not, this is a bounded pause and not a
    poll on the browser's idea of being idle, which a live socket never reaches.
    """
    deadline = time.time() + timeout
    while until is not None and time.time() < deadline:
        if until():
            break
        page.wait_for_timeout(120)
    page.wait_for_timeout(1200)


def node(page: Any, node_id: str) -> Any:
    """The React Flow node for a document path."""
    return page.locator(f'.react-flow__node[data-id="{node_id}"]')


def block(page: Any, path: str) -> Any:
    """The block inside a node: what it says, and what can be done to it."""
    return page.locator(f'[data-path="{path}"]')


def retype(page: Any, field: Any, text: str) -> None:
    """Replace a field's contents the way a person does.

    Click into it, select what is there, type the replacement. ``fill()`` sets
    ``value`` and dispatches one event without the field ever having been
    focused, which is the part of an editor that breaks silently.
    """
    field.click()
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type(text)


def drag(page: Any, source: Any, target: Any) -> None:
    """Drag one element onto another, slowly enough to be a drag.

    The canvas arms a drop zone on movement rather than on the press, and shows
    the insertion point only while a drag is running, so a single jump from
    source to target lands on a canvas that never entered the dragging state.
    """
    start = source.bounding_box()
    end = target.bounding_box()
    assert start and end, (start, end)
    from_x, from_y = start["x"] + start["width"] / 2, start["y"] + start["height"] / 2
    to_x, to_y = end["x"] + end["width"] / 2, end["y"] + end["height"] / 2
    page.mouse.move(from_x, from_y)
    page.mouse.down()
    for step in range(1, 15):
        page.mouse.move(from_x + (to_x - from_x) * step / 14, from_y + (to_y - from_y) * step / 14)
        page.wait_for_timeout(22)
    page.mouse.up()


def zoom_onto(page: Any, node_id: str, turns: int = 4) -> None:
    """Zoom the canvas in beside a node, the way a reader with a wheel does.

    A whole level fits the canvas at about two thirds scale, which is legible
    and not what a screenshot of a *form* should show. React Flow zooms toward
    the pointer, so this is the reader's own gesture and it lands on the node
    rather than on the middle of the canvas.

    *Beside* and not on: the library marks every node view ``nowheel``, and
    React Flow's own filter drops a wheel event from inside one. The margin the
    lane keeps around a block is canvas, and a wheel there zooms.
    """
    box = node(page, node_id).bounding_box()
    page.mouse.move(box["x"] - 8, box["y"] + box["height"] / 2)
    for _ in range(turns):
        page.mouse.wheel(0, -260)
        page.wait_for_timeout(180)
    page.wait_for_timeout(600)


def fields_of(editor: prf.PanelReactFlowEditor, path: str) -> list[Any]:
    """The Panel widgets living inside one node.

    Asserted on directly, because ``FloatInput`` and ``IntInput`` both render
    as ``<input type="number">`` and the difference between them is what this
    variant was faulted for: the DOM says which is there only by its step.
    """
    for node in editor.flow.nodes:
        if node["id"] == path:
            return list(node["view"].objects[1])
    raise AssertionError(f"no node at {path}")


def shown(target: Any) -> str:
    """What an element says, or ``""`` when it is not on the page yet.

    A gesture is two round trips, the model's and the browser's, and a wait
    written against the first reads the page during the second. Every
    assertion about what is drawn waits on what is drawn.
    """
    return (target.text_content() or "") if target.count() else ""


def attribute(target: Any, name: str) -> str:
    """One attribute of an element, or ``""`` when it is not there yet."""
    return (target.get_attribute(name) or "") if target.count() else ""


def styled(target: Any, *properties: str) -> dict[str, str]:
    """The computed style of an element, which is the only thing a reader sees.

    A class name is not a colour. Both the refusal a reorder raises and the
    warning a rewrite raises were asserted on their classes and both passed
    while the stylesheet carrying them was attached to a layout whose shadow
    root the spans are not in, so one rendered in the same grey as "added" and
    the other ran into the word before it.
    """
    return target.evaluate(
        "(el, names) => { const s = getComputedStyle(el); const out = {};"
        " for (const name of names) out[name] = s[name]; return out }",
        list(properties),
    )


def blank_lines(text: str) -> int:
    """How many lines of *text* carry nothing, which is what a rewrite costs."""
    return sum(1 for line in text.splitlines() if not line.strip())


def still_runs(editor: prf.PanelReactFlowEditor) -> None:
    """Execute the module as it now stands, which is the only real assertion.

    The move this exists for reported "moved", changed nothing a reader could
    see, and left a file raising ``NameError: name 'dataclass' is not defined``.
    Every structural edit here is followed by this.
    """
    exec(compile(editor.model.source, "<m>", "exec"), {})  # noqa: S102 - running it is the assertion


def inside(outer: dict[str, float], inner: dict[str, float], slack: float = 2.0) -> bool:
    """Whether one rectangle encloses another, which is what a container claims."""
    return (
        inner["x"] >= outer["x"] - slack
        and inner["y"] >= outer["y"] - slack
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + slack
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + slack
    )


# -- the two questions this variant exists to answer ---------------------------


def test_the_typed_form_is_inside_the_node_and_there_is_no_side_panel(page, live, shots):
    """The first question, and the reason this library was chosen.

    Every other variant renders ``ChargeParam(target_voltage=4.2, c_rate=0.35)``
    as a node with a name on it and puts the two fields in a panel beside the
    canvas. Here they are two ``panel.widgets.FloatInput``\\ s in the node's own
    ``view``, so the assertion is geometric and not merely that a form exists
    somewhere: both inputs are inside the node's rectangle.
    """
    editor = open_editor(page, live)

    holder = node(page, CHARGE)
    box = holder.bounding_box()
    fields = holder.locator(".awl-field input")
    assert fields.count() == 2, "both of the constructor's fields are on the node"

    labels = holder.locator(".awl-field label").all_text_contents()
    assert any("target_voltage" in text for text in labels), labels
    assert any("c_rate" in text for text in labels), labels
    assert {fields.nth(0).input_value(), fields.nth(1).input_value()} == {"4.2", "0.35"}

    for index in range(2):
        assert inside(box, fields.nth(index).bounding_box()), (
            "the field is inside the node's rectangle, not beside the canvas"
        )

    # And nothing is selected to make it appear: the library's own side panel is
    # declined, so there is no second form anywhere on the page.
    assert page.locator(".react-flow__panel .rf-node-view-wrapper").count() == 0
    assert editor.flow.editor_mode == "node"

    # Two turns, not four: the shot has to hold the whole node with both fields
    # in it, and this variant's node is as wide as its lane.
    zoom_onto(page, CHARGE, turns=2)
    grown = holder.bounding_box()
    assert grown["width"] > box["width"] * 1.4, "zoomed in far enough for the shot to show the form"
    assert inside(grown, fields.nth(0).bounding_box()), "and the fields are still in the node"
    page.screenshot(path=str(shots / "02-form.png"))


def test_a_field_inside_the_node_writes_one_line_and_keeps_the_other(page, live, shots):
    """Typed in the node, written back by span: one line changes, ``c_rate`` lives."""
    editor = open_editor(page, live)
    before = editor.model.source.splitlines()
    zoom_onto(page, CHARGE)

    field = node(page, CHARGE).locator(".awl-field input").nth(0)
    assert field.input_value() == "4.2"
    retype(page, field, "4.35")
    page.keyboard.press("Enter")
    settle(page, lambda: "4.35" in editor.model.source)

    after = editor.model.source.splitlines()
    changed = [n for n, (was, now) in enumerate(zip(before, after, strict=True)) if was != now]
    assert len(changed) == 1, after
    assert "target_voltage=4.35" in after[changed[0]]
    assert "c_rate=0.35" in after[changed[0]], "the field beside it was not rewritten"
    assert "4.35" in source_text(page), "the source pane followed"
    assert node(page, CHARGE).locator(".awl-field input").nth(0).input_value() == "4.35", (
        "and the field on the node shows what the file now says"
    )

    page.screenshot(path=str(shots / "03-edited.png"))


def test_the_loop_is_a_region_that_encloses_its_body(page, live, shots):
    """The second question: Sequential Workflow Designer's containers, on React Flow.

    React Flow lays nothing out, which is what makes this a choice rather than a
    default. The claim is checked against rectangles: every statement in the
    loop's body is inside the loop's box, the statement after it is not, and the
    branch inside is inside both.
    """
    editor = open_editor(page, live)

    loop = node(page, LOOP).bounding_box()
    for path in (CHARGE, BRANCH, "body.7.body.3.body.2", LAST_IN_LOOP):
        assert inside(loop, node(page, path).bounding_box()), f"{path} is inside the loop"
    assert inside(loop, node(page, THEN_LANE).bounding_box()), "and so is the branch's then lane, two deep"
    assert not inside(loop, node(page, "body.7.body.4").bounding_box()), "the statement after the loop is not in it"

    # The region is a real node with a parent relationship, not a drawn box.
    parents = {entry["id"]: entry.get("parentId") for entry in editor.flow.nodes}
    assert parents[LOOP_LANE] == LOOP
    assert parents[CHARGE] == LOOP_LANE
    assert parents[THEN_FIRST] == THEN_LANE

    page.screenshot(path=str(shots / "01-level.png"))


def test_the_branch_is_two_labelled_lanes_side_by_side(page, live):
    """An ``if`` splits into ``then`` and ``else`` columns that rejoin below.

    Not two labelled edges leaving one node, which is what React Flow gives you
    if you let it. And the lanes carry the plan's word for how control enters
    them, so nothing on the canvas is a label chosen here.
    """
    open_editor(page, live)

    then_lane = node(page, THEN_LANE).bounding_box()
    else_lane = node(page, ELSE_LANE).bounding_box()
    assert then_lane["x"] + then_lane["width"] <= else_lane["x"] + 2, "side by side, then on the left"
    assert abs(then_lane["y"] - else_lane["y"]) < 3, "and at the same height"

    branch = node(page, BRANCH).bounding_box()
    assert inside(branch, then_lane) and inside(branch, else_lane), "both inside the branch's own region"

    assert node(page, THEN_LANE).locator(".awl-lane-name").text_content() == "then"
    assert node(page, ELSE_LANE).locator(".awl-lane-name").text_content() == "else"
    assert node(page, THEN_LANE).locator(".awl-lane-kind").text_content() == "when_true"
    assert node(page, LOOP_LANE).locator(".awl-lane-kind").text_content() == "when_true"

    # They rejoin, once, below the container. The edge out of the last block in
    # the `then` lane is not drawn as well: the `if` already points at the
    # statement after it, so a second arrow from inside the lane is the same
    # journey drawn twice, and it is the one that has to cross two borders.
    ends = {(edge["source"], edge["target"]) for edge in _editor_of(page, live).flow.edges}
    assert (BRANCH, "body.7.body.3.body.2") in ends
    assert (THEN_FIRST, "body.7.body.3.body.2") not in ends


def _editor_of(page: Any, live: _Live) -> prf.PanelReactFlowEditor:
    assert live.editor is not None
    return live.editor


def test_the_drop_zone_lights_up_and_the_block_lands_in_the_loop(page, live, shots):
    """Snappy drop zones, which is the third thing SWD had and React Flow did not.

    A drag from the toolbox arms the strip under the pointer, and the strip
    already knows the document path it writes into, so this asserts both: that
    it lit up, and that what was dropped went into the loop's body and not
    beside it.
    """
    editor = open_editor(page, live)
    before = editor.model.source.count("rest(600)")

    item = page.locator('[data-tool="call"]')
    target = page.locator('[data-zone="body.7.body.3.body:4"]')
    start = item.bounding_box()
    end = target.bounding_box()
    assert start and end

    # Half way through the drag, the strip under the pointer is armed.
    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    for step in range(1, 15):
        page.mouse.move(
            start["x"]
            + start["width"] / 2
            + (end["x"] + end["width"] / 2 - start["x"] - start["width"] / 2) * step / 14,
            start["y"]
            + start["height"] / 2
            + (end["y"] + end["height"] / 2 - start["y"] - start["height"] / 2) * step / 14,
        )
        page.wait_for_timeout(22)
    armed = page.locator(".awl-zone.awl-armed")
    assert armed.count() == 1, "exactly one insertion point is highlighted under the pointer"
    assert armed.get_attribute("data-zone") == "body.7.body.3.body:4"
    page.screenshot(path=str(shots / "07-dropping.png"))
    page.mouse.up()

    settle(page, lambda: editor.model.source.count("rest(600)") == before + 1)
    assert editor.error == "", editor.error
    assert editor.model.source.count("rest(600)") == before + 1, "a statement was added"
    body = [line for line in editor.model.source.splitlines() if line.startswith("        ")]
    assert sum(1 for line in body if line.strip() == "rest(600)") == 2, "and it landed inside the loop"

    landed = "body.7.body.3.body.4"
    page.wait_for_selector(f'.react-flow__node[data-id="{landed}"]', timeout=20_000)
    assert page.locator(f'[data-edit="{landed}"]').input_value() == "rest(600)"
    assert inside(node(page, LOOP).bounding_box(), node(page, landed).bounding_box()), (
        "and the block that appeared is inside the loop's region, not beside it"
    )
    page.screenshot(path=str(shots / "08-added.png"))


# -- every block editable, removable, addable ----------------------------------


def test_every_kind_of_block_is_editable_through_its_own_source(page, live):
    """``while``, ``if``, ``return`` and a bare assignment, none of which has a form.

    A container offers its *condition*, because the source a ``while`` covers is
    the whole loop and a one-line field over that would be a Python editor with
    extra steps. Everything else offers the line it is. Both reparse like any
    other source edit.
    """
    editor = open_editor(page, live)

    retype(page, page.locator(f'[data-edit="{LOOP}"]'), "i < cycles - 1")
    page.keyboard.press("Enter")
    settle(page, lambda: "while i < cycles - 1:" in editor.model.source)
    assert "while i < cycles - 1:" in editor.model.source, "a loop's test"

    retype(page, page.locator(f'[data-edit="{BRANCH}"]'), "peak >= report.peak_voltage")
    page.keyboard.press("Enter")
    settle(page, lambda: "if peak >= report.peak_voltage:" in editor.model.source)
    assert "if peak >= report.peak_voltage:" in editor.model.source, "a branch's test"

    retype(page, page.locator('[data-edit="body.7.body.2"]'), "i = 1")
    page.keyboard.press("Enter")
    settle(page, lambda: "    i = 1\n" in editor.model.source)
    assert "    i = 1\n" in editor.model.source, "a bare assignment"

    retype(page, page.locator('[data-edit="body.7.body.5"]'), "return None")
    page.keyboard.press("Enter")
    settle(page, lambda: "    return None\n" in editor.model.source)
    assert "    return None\n" in editor.model.source, "a return"
    assert not editor.reformats, "and every one of them was spliced by span, not regenerated"
    assert editor.error == "", editor.error


def test_typing_survives_the_round_trip_a_click_into_a_field_starts(page, live):
    """Clicking into a block's field is a selection, and a selection is a
    parameter arriving back from Python a moment later.

    Repainting the block on one put the file's text back over what was being
    typed, two keystrokes in, and it showed up as one flaky test in four rather
    than as the field emptying itself that it is.
    """
    editor = open_editor(page, live)
    field = page.locator('[data-edit="body.7.body.2"]')
    field.click()
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type("i = 7", delay=0)
    page.wait_for_timeout(1800)  # the round trip the click started lands in here

    assert field.input_value() == "i = 7", "the caret kept what was typed into it"
    page.keyboard.press("Enter")
    settle(page, lambda: "i = 7" in editor.model.source)
    assert "    i = 7\n" in editor.model.source
    assert editor.error == "", editor.error


def test_a_block_can_be_removed_through_the_canvas(page, live):
    """Including one inside a branch, two containers deep."""
    editor = open_editor(page, live)

    page.locator(f'[data-delete="{THEN_FIRST}"]').click()
    settle(page, lambda: "report.peak_voltage = peak" not in editor.model.source)

    assert editor.error == "", editor.error
    assert "report.peak_voltage = peak" not in editor.model.source
    assert "pass" in editor.model.source, "the branch it emptied is still a suite"
    assert editor.reformats, "and it says the write-back reformatted the file"


def test_a_block_can_be_dragged_out_of_the_loop(page, live):
    """The other direction, which is the same claim: what a container holds is
    the model rather than a picture of one.
    """
    editor = open_editor(page, live)
    drag(page, page.locator(f'[data-grip="{LAST_IN_LOOP}"]'), page.locator('[data-zone="body.7.body:5"]'))
    settle(
        page,
        lambda: (
            not any(
                line.strip() == "i += 1" and line.startswith("        ") for line in editor.model.source.splitlines()
            )
        ),
    )

    assert editor.error == "", editor.error
    lines = [line for line in editor.model.source.splitlines() if line.strip() == "i += 1"]
    assert lines, editor.model.source
    assert not lines[0].startswith("        "), "the increment is no longer inside the loop"


def test_a_statement_can_be_dropped_into_either_lane_of_a_branch(page, live, shots):
    """Dropping into the ``else`` raised ``KeyError: 'orelse'``.

    An empty statement list is not in the document at all:
    :func:`awl.compact.encode` drops an empty required list, so an ``if`` with
    no ``else`` carries no ``orelse`` key, and the lane the canvas draws for it
    has no slot behind it. The slot is made by the edit that needs one, in
    :func:`awl.editor.add_step`, which is where the encoding is written; the
    canvas asking for the key first is what turned a drop into a stack trace.

    Both lanes, because a fix that resolved a missing ``orelse`` to ``body``
    would put the statement in the ``then`` and report success.
    """
    editor = open_editor(page, live)
    assert "orelse" not in editor._at(tree.path_of(BRANCH)), "the sample's `if` has no else to begin with"

    drag(page, page.locator('[data-tool="call"]'), page.locator(f'[data-zone="{BRANCH}.orelse:0"]'))
    settle(page, lambda: editor.status == "added")
    assert editor.error == "", editor.error

    landed = f"{BRANCH}.orelse.0"
    page.wait_for_selector(f'.react-flow__node[data-id="{landed}"]', timeout=20_000)
    assert page.locator(f'[data-edit="{landed}"]').input_value() == "rest(600)"
    assert inside(node(page, ELSE_LANE).bounding_box(), node(page, landed).bounding_box()), (
        "the block that appeared is in the else lane, on the canvas and not only in the model"
    )
    assert node(page, f"{THEN_FIRST}").count() == 1, "and the then lane still holds what it held"
    assert page.locator(f'[data-edit="{THEN_FIRST}"]').input_value() == "report.peak_voltage = peak"

    body = editor.model.source.split("if peak > report.peak_voltage:\n")[1].splitlines()
    assert [line.strip() for line in body[:3]] == ["report.peak_voltage = peak", "else:", "rest(600)"], body[:3]
    still_runs(editor)

    zoom_onto(page, BRANCH, turns=2)
    page.screenshot(path=str(shots / "27-dropped-into-else.png"))

    # And into the `then`, which has a slot and never raised, so this is the
    # half that says the fix did not send everything to `body`.
    drag(page, page.locator('[data-tool="assignment"]'), page.locator(f'[data-zone="{BRANCH}.body:1"]'))
    settle(page, lambda: editor.status == "added" and node(page, f"{BRANCH}.body.1").count() == 1)
    assert editor.error == "", editor.error
    assert page.locator(f'[data-edit="{BRANCH}.body.1"]').input_value() == "value = 0"
    assert inside(node(page, THEN_LANE).bounding_box(), node(page, f"{BRANCH}.body.1").bounding_box())
    still_runs(editor)


def test_a_placed_block_can_be_dragged_into_the_else_lane_and_out_again(page, live, shots):
    """A move into an empty ``else`` is an insert into a slot that is not there.

    Same cause as the drop, and worth its own test because it is a different
    gesture and a different code path: the block is carried by its chip, the
    delete renumbers the list it came from, and the insert path has to be
    corrected for that before it is applied.

    Out again as well, because that is what says the edit is reversible and that
    the ``else`` disappears with its last statement rather than turning into
    ``else: pass``.
    """
    editor = open_editor(page, live)

    drag(page, page.locator(f'[data-grip="{LAST_IN_LOOP}"]'), page.locator(f'[data-zone="{BRANCH}.orelse:0"]'))
    settle(page, lambda: editor.status == "moved")
    assert editor.error == "", editor.error

    landed = f"{BRANCH}.orelse.0"
    page.wait_for_selector(f'.react-flow__node[data-id="{landed}"]', timeout=20_000)
    assert page.locator(f'[data-edit="{landed}"]').input_value() == "i += 1"
    assert inside(node(page, ELSE_LANE).bounding_box(), node(page, landed).bounding_box()), (
        "the canvas moved it, not only the model"
    )
    indents = [len(line) - len(line.lstrip()) for line in editor.model.source.splitlines() if line.strip() == "i += 1"]
    assert indents == [12], f"one of it, and one indent deeper than the loop body it left: {indents}"
    still_runs(editor)

    zoom_onto(page, BRANCH, turns=2)
    page.screenshot(path=str(shots / "28-moved-into-else.png"))

    drag(page, page.locator(f'[data-grip="{landed}"]'), page.locator('[data-zone="body.7.body.3.body:3"]'))
    settle(page, lambda: editor.status == "moved" and node(page, landed).count() == 0)
    assert editor.error == "", editor.error
    assert node(page, landed).count() == 0, "the else lane is empty again"
    assert page.locator(f'[data-edit="{LAST_IN_LOOP}"]').input_value() == "i += 1"
    assert "else:" not in editor.model.source, "and an `if` with an empty else is an `if`, not `else: pass`"
    still_runs(editor)


def test_a_container_can_be_added_from_the_toolbox(page, live):
    """A loop is a block like any other, and dropping one produces a region with
    a lane inside it: the nesting is the model, so there is nowhere else it
    could go.
    """
    editor = open_editor(page, live)
    drag(page, page.locator('[data-tool="loop"]'), page.locator('[data-zone="body.7.body:5"]'))
    settle(page, lambda: "while False:" in editor.model.source)

    assert editor.error == "", editor.error
    assert "while False:" in editor.model.source
    page.wait_for_selector('.react-flow__node[data-id="lane:body.7.body.5.body"]', timeout=20_000)
    assert node(page, "body.7.body.5").count() == 1
    assert node(page, "lane:body.7.body.5.body").count() == 1, "with a lane of its own"
    assert node(page, "body.7.body.5.body.0").count() == 1, "and a statement in it"


# -- the plan's edges ----------------------------------------------------------


def test_the_loops_repeat_is_read_from_the_plan_and_expressed_by_the_container(page, live):
    """Derived, not decorative, and now expressed rather than drawn.

    The plan reports a ``repeat`` from the loop's last statement back to its
    header. The region drawn around the body is what says the body repeats, so
    the arc said it a second time, dashed, across the whole height of the loop
    and through a 46 pixel gutter kept empty for it.

    What is asserted is both halves. The plan's edge is there, and the canvas
    read it: ``enclosed`` names the statement it leaves and the word the plan
    gave it, so a canvas that simply stopped looking at ``repeat`` would fail
    here. And nothing is drawn for it.
    """
    editor = open_editor(page, live)

    plan = editor.model.flow("procedure")["edges"]
    steps = {step["id"]: tree.span_key(step.get("span")) for step in editor.model.flow("procedure")["steps"]}
    repeats = [edge for edge in plan if edge["kind"] == "repeat"]
    assert len(repeats) == 1, repeats
    assert steps[repeats[0]["from"]] == tree.span_key(editor._blocks[LAST_IN_LOOP].span)
    assert steps[repeats[0]["to"]] == tree.span_key(editor._blocks[LOOP].span)

    assert editor.enclosed == {LAST_IN_LOOP: "repeat"}, "the canvas saw it and says which block it leaves"
    assert [edge for edge in editor.flow.edges if edge["data"]["drawn"] == "back"] == []
    assert page.locator(".react-flow__edge-text", has_text="repeat").count() == 0

    # And the gutter it ran in is gone with it, so the loop is no wider than
    # what it holds. Kept, it is a strip of empty canvas for an arc nobody draws.
    loop = editor.boxes[LOOP]
    lane = editor.boxes[LOOP_LANE]
    assert loop[0] + loop[2] - (lane[0] + lane[2]) < 20, (loop, lane)


def test_a_level_whose_plan_has_no_repeat_draws_no_arc(page, live):
    """The other half of "derived": nothing to draw, nothing drawn.

    Module scope has a loop nowhere in it, so it gets no arc, and it does have
    the one ``next`` its plan reports, between the docstring and the import,
    which is the difference between "draws no back edge" and "draws nothing".
    """
    editor = open_editor(page, live)
    page.locator(".awl-crumb button", has_text="awl.ui.sample").click()
    settle(page, lambda: editor.scope == "")

    assert [edge for edge in editor.flow.edges if edge["data"]["drawn"] == "back"] == []
    assert [edge["data"]["kind"] for edge in editor.flow.edges] == ["next"], editor.flow.edges
    assert page.locator(".react-flow__edge").count() == 1
    assert page.locator(".react-flow__edge-text").count() == 0, "and a plain `next` is not labelled"


def test_an_edge_the_layout_cannot_express_is_still_drawn_as_an_arc():
    """Almost every edge the plan reports is now a lane label, a container or a
    straight connector, and a ``break`` is the one that is none of them.

    It leaves a branch inside a loop and lands after the loop, which is not
    where falling out of either would take it, so there is nothing on the canvas
    that already says it and it is drawn: out to the right, up the gutter, back
    in. The gutter goes on both containers it has to escape, because a strip
    kept clear beside one of them leaves the arc crossing the other.

    Kept and tested rather than deleted with the loop's ``repeat``. An edge the
    canvas cannot place must be visible; the alternative is a plan edge that
    silently disappears the first time a procedure has a shape this has not met.
    """
    model = ui.load(
        "def p(a, b):\n    while a:\n        if b:\n            break\n        c = 1\n    d = 2\n    return d\n",
        module="m",
        file="m.py",
    )
    editor = prf.PanelReactFlowEditor(model, scope="p")
    wiring = layout.edges_for(editor.tree, model.flow("p")["edges"])

    loop, branch, leaving = "body.0.body.0", "body.0.body.0.body.0", "body.0.body.0.body.0.body.0"
    arcs = [edge for edge in editor.flow.edges if edge["data"]["drawn"] == "back"]
    assert [(edge["source"], edge["target"]) for edge in arcs] == [(leaving, "body.0.body.1")], arcs
    assert wiring.escaping == {loop, branch}, wiring.escaping

    for container, held in ((loop, f"lane:{loop}.body"), (branch, f"lane:{branch}.body")):
        outer, inner = editor.boxes[container], editor.boxes[held]
        assert outer[0] + outer[2] - (inner[0] + inner[2]) >= layout.GEOMETRY["gutter"], (container, outer, inner)

    assert editor.legs[arcs[0]["id"]] > editor.boxes[leaving][0] + editor.boxes[leaving][2], (
        "and the leg the library will draw is clear of the block it leaves"
    )


def test_a_for_loop_says_what_the_plan_calls_its_edges():
    """``each_item`` and ``exhausted``, not ``when_true`` and ``when_false``.

    The sample has no ``for``, so this is asserted on a module written for it. A
    canvas that hard-coded the lane labels would write a ``while``'s words over
    a ``for``'s body and nothing would say so.
    """
    model = ui.load(
        "def total(items):\n    running = 0\n    for item in items:\n        running += item\n    return running\n",
        module="m",
        file="m.py",
    )
    editor = prf.PanelReactFlowEditor(model, scope="total")

    assert editor.lane_kinds == {"lane:body.0.body.1.body": "each_item"}
    kinds = {(edge["source"], edge["target"]): edge["data"]["kind"] for edge in editor.flow.edges}
    assert kinds[("body.0.body.1", "body.0.body.2")] == "exhausted"
    assert editor.enclosed == {"body.0.body.1.body.0": "repeat"}, "and a `for` repeats by the same rule"


# -- where you are -------------------------------------------------------------


def test_every_ancestor_is_on_the_path_navigator(page, live):
    """A navigator whose first entry is where you started is not a navigator."""
    editor = open_editor(page, live)
    assert page.locator(".awl-crumb button").all_text_contents() == ["awl.ui.sample", "procedure"]

    # A crumb has to read as a path and not as a row of buttons, and the class
    # is on the widget's host while the button is inside its shadow root: a
    # rule written as a descendant of the class matched nothing at all.
    assert styled(page.locator(".awl-crumb button").first, "color", "backgroundColor") == {
        "color": "rgb(67, 56, 202)",
        "backgroundColor": "rgba(0, 0, 0, 0)",
    }
    assert styled(page.locator(".awl-sep").first, "color") == {"color": "rgb(148, 163, 184)"}

    page.locator(".awl-crumb button", has_text="awl.ui.sample").click()
    settle(page, lambda: editor.scope == "")
    assert editor.scope == ""


def test_the_navigator_draws_the_containers_you_are_standing_in(page, live, shots):
    """Levels alone said ``awl.ui.sample > procedure`` from inside a branch two
    containers deep: true, and no answer to the question a navigator exists for.
    The containers come from the tree, which already holds the nesting.
    """
    editor = open_editor(page, live)
    assert page.locator(".awl-crumb-in button").count() == 0, "nothing is selected, so you are nowhere in particular"

    block(page, THEN_FIRST).click()
    settle(page, lambda: page.locator(".awl-crumb-in button").count() == 3)
    assert page.locator(".awl-crumb button").all_text_contents() == [
        "awl.ui.sample",
        "procedure",
        "while i < cycles:",
        "if peak > report.peak_voltage:",
        "then",
    ]

    page.screenshot(path=str(shots / "06-nesting.png"))

    block(page, "body.7.body.5").click()
    settle(page, lambda: page.locator(".awl-crumb-in button").count() == 0)
    assert page.locator(".awl-crumb button").all_text_contents() == ["awl.ui.sample", "procedure"], (
        "and it follows the selection back out again"
    )
    assert editor.scope == "procedure"


def test_double_clicking_a_call_opens_the_level_it_names(page, live, shots):
    """Unlimited, because nothing counts depth: a level is a scope, and
    descending produces another scope.
    """
    editor = open_editor(page, live)
    page.locator(f'[data-grip="{CHARGE}"]').dblclick()
    settle(page, lambda: editor.scope == "charge")

    assert editor.scope == "charge"
    assert [entry["label"] for entry in editor.trail] == ["awl.ui.sample", "procedure", "charge"]
    assert page.locator('[data-edit="body.6.body.1"]').input_value() == "voltage = 0.0"
    assert node(page, "body.6.body.2").count() == 1, "and it has a loop of its own"
    assert node(page, "lane:body.6.body.2.body").count() == 1

    page.screenshot(path=str(shots / "04-descended.png"))


def test_the_module_draws_a_block_for_every_level_below_it(page, live, shots):
    """A declaration does not run, so it is not a step and never appeared on a
    canvas that draws what runs. Standing on the module, ``procedure`` is a
    block, and double-clicking it opens the level.
    """
    editor = open_editor(page, live)
    page.locator(".awl-crumb button", has_text="awl.ui.sample").click()
    settle(page, lambda: editor.scope == "")

    levels = page.locator('[data-role="level"] .awl-text-static').all_text_contents()
    assert levels == ["def settle (1)", "def rest (2)", "def charge (5)", "def procedure (11)"], (
        "one block per level below this one, each saying how much is inside it"
    )
    assert page.locator('[data-role="class"]').count() == 2, "a declaration that is not a level is drawn as one"

    page.screenshot(path=str(shots / "09-sublevel.png"))

    # On the label, which is what a level block says and what a reader aims at.
    # The block's other half is its note line, and that is an input: a
    # double-click there selects a word, which is what a double-click in a text
    # field does, so the note stops the descent on purpose.
    page.locator('[data-path="body.7"] .awl-text-static').dblclick()
    settle(page, lambda: editor.scope == "procedure")
    assert editor.scope == "procedure", "and a double-click opens it"


# -- running -------------------------------------------------------------------


def test_running_draws_iterations_and_which_way_the_branch_went(page, live, shots):
    """A real run, traced, joined to the canvas by the span it was drawn from."""
    editor = open_editor(page, live)
    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay))

    assert page.locator('[data-testid="status"]').text_content() == ("ran procedure: 10/11 steps in procedure executed")
    assert block(page, CHARGE).locator(".awl-badge").text_content() == f"{TIMES}3"
    assert block(page, BRANCH).locator(".awl-badge").text_content() == f"{TIMES}3 T+F"
    assert block(page, LOOP).locator(".awl-badge").text_content() == "T+F", "the loop says which way its test went"
    assert block(page, "body.7.body.0").get_attribute("data-state") == "skipped", (
        "the docstring did not run, and is drawn as not having run"
    )

    page.screenshot(path=str(shots / "10-run.png"))


def test_the_overlay_follows_the_level_it_is_drawn_on(page, live, shots):
    """The same run, read at another level. ``charge``'s own loop turned twelve
    times, which is a different number on a different canvas from the three the
    procedure's loop turned. And the status names both levels, because
    ``ran procedure: 4/5`` while ``charge`` is on screen attributes one level's
    numbers to another level's name.
    """
    editor = open_editor(page, live)
    page.locator(f'[data-grip="{CHARGE}"]').dblclick()
    settle(page, lambda: editor.scope == "charge")
    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay))

    assert editor.scope == "charge"
    assert block(page, "body.6.body.2.body.0").locator(".awl-badge").text_content() == f"{TIMES}12"
    assert page.locator('[data-testid="status"]').text_content() == "ran procedure: 4/5 steps in charge executed"

    page.screenshot(path=str(shots / "05-trace.png"))


def test_a_level_the_trace_never_reached_is_not_a_level_that_did_not_run(page, live):
    """Module scope reported ``0/2 steps executed`` and greyed both blocks.

    The module's own statements run when the module is executed, which is before
    the tracer is installed, so the run has no observation of them at all.
    Drawing that as "did not run" says the file did nothing.
    """
    editor = open_editor(page, live)
    page.locator(".awl-crumb button", has_text="awl.ui.sample").click()
    settle(page, lambda: editor.scope == "")
    page.locator(".awl-run button").click()
    settle(page, lambda: "ran procedure" in editor.status)

    assert editor.status == "ran procedure: nothing in awl.ui.sample was traced"
    assert editor.overlay == {}
    assert page.locator('[data-state="skipped"]').count() == 0, "nothing is greyed, because nothing was observed"


def test_the_trace_is_cleared_when_the_file_is_reparsed(page, live):
    """A badge keyed on a span that has since moved names the wrong statement.

    That shipped in this comparison once already, so the overlay is dropped on
    every rebuild that is not the run's own, and the assertion is that it is
    gone rather than that it is right.
    """
    editor = open_editor(page, live)
    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay))
    assert block(page, CHARGE).locator(".awl-badge").text_content() == f"{TIMES}3"

    retype(page, page.locator('[data-edit="body.7.body.2"]'), "i = 2")
    page.keyboard.press("Enter")
    settle(page, lambda: "i = 2" in editor.model.source)

    assert editor.overlay == {}
    assert page.locator(".awl-badge:visible").count() == 0, "no badge survives a reparse"


# -- the source pane -----------------------------------------------------------


def test_the_whole_pane_can_be_clicked_into_and_the_caret_lands_where_you_clicked(page, live):
    """Two thirds of one of these could not be clicked into at all.

    Both layers were ``position: absolute; inset: 0`` inside a scrolling parent,
    which sizes them to the *visible* pane rather than to the text, so the
    textarea's hit box covered the first third of the file, and every test
    written with ``fill()`` passed anyway.

    Monaco owns its own scrolling, so the question is no longer whether a click
    lands but whether it lands *where it was aimed*: the assertion is that the
    line Monaco puts the caret on is the line drawn under the pointer, at five
    heights down the pane and again after scrolling to the end of the file.
    """
    open_editor(page, live)

    def clicked_line(fraction: float) -> tuple[int, int]:
        box = page.locator(".awl-source").bounding_box()
        x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * fraction
        drawn = page.evaluate(
            "(at) => { const view = monaco.editor.getEditors()[0];"
            " const p = view.getTargetAtClientPoint(at.x, at.y); return p && p.position ? p.position.lineNumber : 0 }",
            {"x": x, "y": y},
        )
        page.mouse.click(x, y)
        page.wait_for_timeout(120)
        return drawn, caret(page)["line"]

    for fraction in (0.05, 0.35, 0.5, 0.75, 0.95):
        drawn, landed = clicked_line(fraction)
        assert drawn > 0, f"a line is drawn {fraction:.0%} down the pane"
        assert landed == drawn, f"the caret landed on line {landed}, not the line {drawn} under the pointer"

    # And again at the bottom of the file, which is where two layers drift apart.
    page.keyboard.press("ControlOrMeta+End")
    page.wait_for_timeout(300)
    at_end = caret(page)
    lines = page.evaluate("() => monaco.editor.getEditors()[0].getModel().getLineCount()")
    assert at_end["line"] == lines, "the caret is on the last line of the file"

    drawn, landed = clicked_line(0.5)
    assert landed == drawn > 20, "and a click half way down a scrolled pane still lands where it was aimed"


def test_the_source_is_highlighted_by_monacos_own_python_grammar(page, live):
    """Zero highlight spans is a shipped failure in this comparison, not a risk.

    One variant paid 229 KB and 38 requests for CodeMirror and rendered no
    highlighting at all, because a ``?deps=`` pin omitted ``@codemirror/language``
    and its tests asserted on the markup rather than on what a reader sees. So
    this asserts on the **computed colour**: keywords, strings and numbers are
    each drawn in a colour of their own, and none of them is the colour of plain
    text.

    panelini's MonacoEditor would fail exactly here. Its bundle carries the JSON
    and YAML contributions and nothing else, so ``python`` is a language Monaco
    has never been told about and every token comes back unstyled.
    """
    open_editor(page, live)
    spot(page, "def procedure")

    painted = page.evaluate("""() => {
      const found = []
      const walk = root => {
        for (const el of root.querySelectorAll('*')) {
          if (el.matches('.view-line span')) found.push(el)
          if (el.shadowRoot) walk(el.shadowRoot)
        }
      }
      walk(document)
      const seen = {}
      for (const el of found) {
        const word = el.textContent.trim()
        if (!word) continue
        seen[word] = seen[word] || getComputedStyle(el).color
      }
      return seen
    }""")

    keyword = painted.get("def") or painted.get("while") or painted.get("return")
    assert keyword, f"no keyword was drawn at all: {sorted(painted)[:20]}"
    plain = painted.get("procedure") or painted.get("report")
    assert plain, sorted(painted)[:20]
    assert keyword != plain, f"keywords are drawn in {keyword}, the same colour as a plain name"

    coloured = set(painted.values())
    assert len(coloured) >= 3, f"a Python file has more than two colours in it: {coloured}"


def test_typing_keeps_the_source_highlighted(page, live):
    """The hand-built pane stripped every span on the first keystroke until the
    round trip came back. Monaco tokenizes what it holds, so the question is
    only whether the colours survive a document replaced from Python.
    """
    editor = open_editor(page, live)

    def keywords() -> int:
        return page.evaluate("""() => {
          const found = []
          const walk = root => {
            for (const el of root.querySelectorAll('*')) {
              if (el.matches('.view-line span')) found.push(el)
              if (el.shadowRoot) walk(el.shadowRoot)
            }
          }
          walk(document)
          return found.filter(el => getComputedStyle(el).color === 'rgb(0, 0, 255)').length
        }""")

    before = keywords()
    assert before > 3, before

    click_source(page, 0.3)
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type("\n")
    page.wait_for_timeout(60)  # inside the debounce: nothing has been sent yet
    assert keywords() >= before, "still coloured while the round trip is in flight"

    settle(page, lambda: editor.status == "source applied")
    assert source_text(page) == editor.model.source, "and Python's answer is what the pane now holds"
    assert keywords() >= before, "with its colours"


def test_a_source_edit_redraws_the_canvas(page, live, shots):
    """Both ways, or the source pane is a read-only echo.

    Typed, with the caret walked to the line the way a reader would walk it:
    ``fill()`` never places one, and where the caret goes is what was broken.
    Monaco indents the new line itself, which the textarea could not, so the
    indentation is no longer typed out.
    """
    editor = open_editor(page, live)
    where = spot(page, "i += 1")
    page.mouse.click(where["x"], where["y"])
    page.keyboard.press("End")
    page.keyboard.type("\nsettle(1)")
    settle(page, lambda: "settle(1)" in editor.model.source)

    assert editor.error == "", editor.error
    page.wait_for_selector('.react-flow__node[data-id="body.7.body.3.body.4"]', timeout=20_000)
    assert node(page, "body.7.body.3.body.4").count() == 1, "the new statement is inside the loop it was typed into"
    assert page.locator('[data-edit="body.7.body.3.body.4"]').input_value() == "settle(1)"
    assert inside(node(page, LOOP).bounding_box(), node(page, "body.7.body.3.body.4").bounding_box())

    page.screenshot(path=str(shots / "11-source-edit.png"))


def test_source_that_does_not_parse_changes_nothing_and_says_where(page, live):
    """A half-typed edit is the normal state of a source pane.

    The canvas is untouched, and the failure is underlined where it happened
    rather than only written in the bar: a notice reading ``line 69`` beside a
    pane showing line 12 is a reader's problem.
    """
    editor = open_editor(page, live)
    before = editor.model.source
    drawn = page.locator(".react-flow__node").count()

    click_source(page, 0.3)
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type("\nif")
    settle(page, lambda: bool(editor.error))

    status = page.locator('[data-testid="status"]').text_content()
    assert status.startswith("line "), status
    assert editor.model.source == before
    assert page.locator(".react-flow__node").count() == drawn, "the canvas still has what it had"

    own = markers(page, "awl")
    assert len(own) == 1, own
    assert own[0]["message"].startswith("awl cannot parse this:"), own
    lines = page.evaluate("() => monaco.editor.getEditors()[0].getModel().getLineCount()")
    assert own[0]["line"] == lines, f"underlined on the line that was typed, not somewhere else: {own}"


# -- taking it back ------------------------------------------------------------


def test_undo_puts_the_file_back_and_the_canvas_with_it(page, live):
    """Undo goes through the model, because the canvas is drawn from the document
    and every node on it is identified by its path in that document. An undo the
    file does not know about leaves a canvas whose every id names a statement
    that has moved, after which every later edit addresses the previous
    version of the file.
    """
    editor = open_editor(page, live)
    before = editor.model.source
    assert page.locator(".awl-undo button").is_disabled(), "nothing has been edited yet"

    page.locator('[data-delete="body.7.body.4"]').click()
    settle(page, lambda: "report.cycles = i" not in editor.model.source)
    assert "report.cycles = i" not in editor.model.source

    page.locator(".awl-undo button").click()
    settle(page, lambda: editor.model.source == before)

    assert editor.model.source == before, "the file is what it was"
    assert page.locator('[data-edit="body.7.body.5"]').input_value() == "return report", (
        "and the paths on the canvas address the file that now exists"
    )
    assert page.locator(".awl-undo button").is_disabled(), "with nothing left to take back"


def test_a_gesture_that_changed_nothing_is_not_worth_an_undo(page, live):
    """A source edit that does not parse is a gesture and not an edit."""
    editor = open_editor(page, live)
    click_source(page, 0.3)
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type("\nif")
    settle(page, lambda: bool(editor.error))

    assert page.locator('[data-testid="status"]').text_content().startswith("line ")
    assert page.locator(".awl-undo button").is_disabled(), "nothing changed, so there is nothing to take back"


# -- reorder is not an index ---------------------------------------------------


def test_moving_the_import_below_a_class_is_refused_and_says_so(page, live, shots):
    """The worst shape a defect can take: silent, and blamed on the file.

    Dragging the import below a class reported "moved", changed nothing a
    reader could see, and left a module raising ``NameError: name 'dataclass'
    is not defined``. A statement list holds declarations that are not steps,
    so position in the list is not position in the flow, and the refusal has to
    be visible or it is the same defect with a different notice.
    """
    editor = open_editor(page, live)
    page.locator(".awl-crumb button", has_text="awl.ui.sample").click()
    settle(page, lambda: editor.scope == "")
    before = editor.model.source

    notice = page.locator('[data-testid="status"]')
    drag(page, page.locator('[data-grip="body.1"]'), page.locator('[data-zone="body:3"]'))
    settle(page, lambda: "dataclass" in shown(notice))

    assert "dataclass is a declaration" in notice.text_content(), notice.text_content()
    assert notice.is_visible()
    assert styled(notice, "color", "fontWeight") == {"color": "rgb(185, 28, 28)", "fontWeight": "600"}, (
        "drawn as a refusal and not as a notice, in the colour a reader sees rather than a class name"
    )
    assert editor.status == "", "nothing is claiming the move happened"

    assert editor.model.source == before, "the file was not touched"
    assert not editor.model.reformats(), "and nothing is pending that would rewrite it later"
    assert page.locator('[data-edit="body.1"]').input_value() == "from dataclasses import dataclass", (
        "the import is where it was"
    )
    still_runs(editor)

    page.screenshot(path=str(shots / "12-refused.png"))


def test_a_block_cannot_be_carried_above_the_docstring_of_the_level_it_lands_in(page, live):
    """The other half of the same rule, across two lists rather than within one.

    A docstring is not a step either, and a statement moved above one turns it
    into a bare string expression: the function stops having a docstring and
    nothing on the canvas would say so.
    """
    editor = open_editor(page, live)
    before = editor.model.source

    drag(page, page.locator(f'[data-grip="{LAST_IN_LOOP}"]'), page.locator('[data-zone="body.7.body:0"]'))
    settle(page, lambda: bool(editor.error))

    assert "docstring" in editor.error, editor.error
    assert editor.model.source == before
    assert not editor.model.reformats()
    still_runs(editor)


def test_a_refused_drop_from_the_toolbox_leaves_nothing_pending():
    """Refused before anything is applied, and not applied and taken back again.

    An append undone by a delete is two structural patches that cancel out, and
    ``to_source`` cannot see that they do: the file was intact and the *next*
    value edit anywhere in it would have regenerated the whole module.
    """
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="")
    before = editor.model.source

    editor.command({"op": "insert", "into": "body", "index": 1, "kind": "assignment"})

    assert "dataclass is a declaration" in editor.error, editor.error
    assert editor.model.source == before
    assert editor.model.edits == [], "nothing was applied, so there is nothing to write back"
    assert not editor.model.reformats()
    still_runs(editor)


def test_a_move_within_the_flow_is_still_allowed():
    """The refusal is about declarations and docstrings, not about moving."""
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="procedure")
    editor.command({"op": "move", "path": "body.7.body.3.body.2", "into": "body.7.body.3.body", "index": 0})

    assert editor.error == "", editor.error
    assert editor.status == "moved"
    body = editor.model.source.split("while i < cycles:\n")[1].splitlines()
    assert body[0].strip() == "rest(600)", body
    still_runs(editor)


# -- the two tiers of write-back -----------------------------------------------


def test_a_structural_edit_counts_what_rewriting_the_file_took(page, live, shots):
    """``reformats()`` was computed on every structural edit and drawn nowhere.

    One insert took nine blank lines out of the module while the notice said
    only "added", which is the reader finding it in a diff instead of on the
    screen.

    What it then said was "comments and blank lines not preserved", every time,
    whatever had happened. That is a claim made in advance about every rewrite,
    and a warning that fires over a file with no comment in it is a warning that
    stops being read. It is counted on the file now, before and against after,
    so the assertion here is that the numbers in the notice are the numbers in
    the module.
    """
    editor = open_editor(page, live)
    before = editor.model.source
    assert page.locator('[data-testid="reformats"]').count() == 0, "nothing has been rewritten yet"

    # A comment first, written through the canvas, so there is one to lose.
    retype(page, page.locator('[data-note="body.7.body.2"]'), "the cycle counter")
    page.keyboard.press("Enter")
    settle(page, lambda: "the cycle counter" in editor.model.source)
    assert not editor.reformats, "a note is a span patch and costs the file nothing"
    written = editor.model.source

    warning = page.locator('[data-testid="reformats"]')
    drag(page, page.locator('[data-tool="call"]'), page.locator('[data-zone="body.7.body.3.body:4"]'))
    settle(page, lambda: editor.status == "added" and warning.count() == 1)

    assert editor.status == "added"
    lost = blank_lines(written) - blank_lines(editor.model.source)
    assert lost > 0, "the rewrite really did cost blank lines"
    assert "the cycle counter" not in editor.model.source, "and the comment, which is what the warning is for"

    assert warning.count() == 1, "and the editor said so before the reader found it in a diff"
    assert warning.text_content() == f"rewritten: 1 comment and {lost} blank lines gone", warning.text_content()
    assert warning.is_visible()
    assert styled(warning, "color", "backgroundColor", "marginLeft") == {
        "color": "rgb(146, 64, 14)",
        "backgroundColor": "rgb(254, 243, 199)",
        "marginLeft": "8px",
    }, "and it is drawn as a warning standing apart from the notice, not as more of the same sentence"
    assert blank_lines(before) - blank_lines(editor.model.source) == lost, "counted against the file, not guessed"
    still_runs(editor)

    page.screenshot(path=str(shots / "13-reformats.png"))

    # And it goes away again: a value edit is patched by span, and the warning
    # is about the write-back that just happened rather than a state the file
    # is stuck in.
    retype(page, page.locator('[data-edit="body.7.body.2"]'), "i = 3")
    page.keyboard.press("Enter")
    settle(page, lambda: "i = 3" in editor.model.source and warning.count() == 0)
    assert warning.count() == 0, "a span patch keeps the layout and says nothing"


# -- the widget comes from the declaration -------------------------------------


def test_the_widget_is_the_declared_type_and_not_the_literals(page, live, shots):
    """``target_voltage=4`` is a ``float`` field holding an integer literal.

    Inferring from the literal rendered a spinner that stepped in ones and
    could not express ``4.35`` at all. The class already says what it is, and
    the class is in the document being edited, so nothing has to be imported to
    read it.
    """
    editor = open_editor(page, live)
    assert editor.declared("ChargeParam", "target_voltage") == "float"
    assert editor.declared("Report", "cycles") == "int"
    assert editor.declared("Report", "peak_voltage") == "float"
    assert editor.declared("Nothing", "at_all") == "", "and a field with no declaration asks for none"

    # A float field carrying an integer, typed the way the sample could have
    # been written: this is exactly the case that used to fall back to `int`.
    retype(page, page.locator(f'[data-edit="{CHARGE}"]'), "peak = charge(ChargeParam(target_voltage=4, c_rate=0.35))")
    page.keyboard.press("Enter")
    settle(page, lambda: "target_voltage=4," in editor.model.source)
    assert "target_voltage=4," in editor.model.source, editor.model.source

    kinds = [type(widget).__name__ for widget in fields_of(editor, CHARGE)]
    assert kinds == ["FloatInput", "FloatInput"], kinds
    assert [type(widget).__name__ for widget in fields_of(editor, "body.7.body.1")] == ["IntInput", "FloatInput"], (
        "and an int-declared field is still an int input, so the declaration is read rather than ignored"
    )

    zoom_onto(page, CHARGE)
    field = node(page, CHARGE).locator(".awl-field input").nth(0)
    assert field.input_value() == "4", "the field shows the integer the file holds"
    # Shot here and not after the edit below: the state worth a picture is a
    # float field standing over an integer literal, which is what used to
    # render a spinner that stepped in ones.
    page.screenshot(path=str(shots / "14-declared.png"))

    retype(page, field, "4.35")
    page.keyboard.press("Enter")
    settle(page, lambda: "4.35" in editor.model.source)

    assert "target_voltage=4.35" in editor.model.source, "and the field can express it"
    assert field.input_value() == "4.35"


def test_a_declared_type_can_be_asked_for_before_the_first_refresh(monkeypatch):
    """Every typed field in every node asks for one, and the fields are built
    inside ``refresh``: an attribute assigned only there is assigned only
    *sometimes*, and the first thing to ask before it wins gets an
    ``AttributeError`` reported as something else entirely.
    """
    asked: list[str] = []
    original = prf.PanelReactFlowEditor.refresh

    def watching(self, **options):
        asked.append(self.declared("ChargeParam", "target_voltage"))
        return original(self, **options)

    monkeypatch.setattr(prf.PanelReactFlowEditor, "refresh", watching)
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="procedure")

    assert asked == [""], "asked before anything was read, and answered without raising"
    assert editor.declared("ChargeParam", "target_voltage") == "float"


# -- what a call resolved to ---------------------------------------------------


def test_a_call_says_what_it_resolved_to_and_when_it_resolved_to_nothing(page, live, shots):
    """An unread function and an empty one are different claims.

    ``opens()`` is None for both a name that resolved to nothing and a class
    that resolved perfectly well, so a canvas with only that answer labels
    ``Report(...)`` "source not read". Three states, and all three are drawn:
    resolved and openable, resolved and not a level, resolved to nothing.
    """
    editor = open_editor(page, live)

    assert block(page, "body.7.body.1").locator('[data-testid="resolved"]').text_content() == "Report"
    assert block(page, CHARGE).locator('[data-testid="resolved"]').text_content() == "charge"
    assert block(page, CHARGE).locator('[data-testid="resolved"]').get_attribute("title") == "resolves to charge"
    assert block(page, CHARGE).locator("[data-open]").count() == 1, "and that one opens, which the other does not"
    assert block(page, "body.7.body.1").locator("[data-open]").count() == 0
    assert not block(page, "body.7.body.2").locator('[data-testid="resolved"]').is_visible(), (
        "a statement that calls nothing claims nothing"
    )

    # A name nothing in the module declares and nothing imports.
    mark = block(page, "body.7.body.3.body.2").locator('[data-testid="resolved"]')
    retype(page, page.locator('[data-edit="body.7.body.3.body.2"]'), "notify(600)")
    page.keyboard.press("Enter")
    settle(page, lambda: "notify(600)" in editor.model.source and shown(mark) == "unresolved")

    assert mark.text_content() == "unresolved"
    assert mark.get_attribute("title") == "notify resolved to nothing: its source was never indexed"
    assert mark.is_visible()
    resolved = styled(block(page, CHARGE).locator('[data-testid="resolved"]'), "color", "backgroundColor")
    assert styled(mark, "color", "backgroundColor") != resolved, (
        "and a reader can see the difference, not only read the class"
    )
    assert styled(mark, "backgroundColor") == {"backgroundColor": "rgb(254, 243, 199)"}

    page.screenshot(path=str(shots / "15-resolved.png"))


def test_the_three_states_a_call_can_be_in_are_three_different_values():
    """Asserted on the tree as well as on the canvas, because the canvas can
    only draw what the tree collected and ``resolved`` was collected correctly
    and drawn nowhere for as long as this variant existed.
    """
    model = ui.load(
        "from acme import drive\n\n\ndef procedure():\n    helper()\n    drive(1)\n    notify(2)\n"
        "\n\ndef helper():\n    pass\n",
        module="m",
        file="m.py",
    )
    editor = prf.PanelReactFlowEditor(model, scope="procedure")
    found = {found.label: (found.calls, found.resolved, found.opens) for found in tree.walk(editor.tree)}

    assert found["helper()"] == ("helper", "helper", "helper"), "read, and a level"
    assert found["drive(1)"] == ("drive", "acme.drive", ""), "resolved into a module that was never indexed"
    assert found["notify(2)"] == ("notify", "", ""), "resolved to nothing at all"


# -- an insert has to be visible -----------------------------------------------


def test_what_was_inserted_is_selected_and_outlined_on_the_canvas(page, live, shots):
    """ "An insert must give feedback." A notice reading "added" over eleven
    identical blocks is not feedback.

    The ring is the block's own and not React Flow's, because the library keeps
    its idea of the selection in the browser and overwrites what the editor
    sends for any node id it already has: a ring set from Python showed only on
    a node that had just been created, and an insert renumbers the paths after
    it rather than creating one.
    """
    editor = open_editor(page, live)
    drag(page, page.locator('[data-tool="assignment"]'), page.locator('[data-zone="body.7.body.3.body:2"]'))
    settle(page, lambda: editor.status == "added")

    landed = "body.7.body.3.body.2"
    assert editor.error == "", editor.error
    page.wait_for_selector(f'.react-flow__node[data-id="{landed}"]', timeout=20_000)
    assert page.locator(f'[data-edit="{landed}"]').input_value() == "value = 0"

    assert editor.selected == landed
    settle(page, lambda: attribute(block(page, landed), "data-selected") == "1")
    assert block(page, landed).get_attribute("data-selected") == "1", "the browser was told, not only the model"

    outline = node(page, landed).evaluate(
        "el => { const s = getComputedStyle(el); return [s.outlineStyle, s.outlineWidth] }"
    )
    assert outline[0] == "solid" and float(outline[1].rstrip("px")) >= 2, outline

    assert page.locator('.awl-block[data-selected="1"]').count() == 1, "one ring, so the feedback names one block"
    assert page.locator(".react-flow__node[data-awl-selected]").count() == 1

    # And the path bar followed it in, which is the second half of "where did
    # that go": the block is inside the loop and the trail now says so.
    assert page.locator(".awl-crumb button").all_text_contents() == [
        "awl.ui.sample",
        "procedure",
        "while i < cycles:",
    ]
    still_runs(editor)

    page.screenshot(path=str(shots / "16-selected.png"))


def test_a_crumb_for_a_container_selects_it_on_the_canvas(page, live):
    """The same mechanism read from the other end: clicking a nesting crumb has
    to move the canvas, not only the bar it was clicked in.
    """
    editor = open_editor(page, live)
    block(page, THEN_FIRST).click()
    settle(page, lambda: page.locator(".awl-crumb-in button").count() == 3)
    assert block(page, THEN_FIRST).get_attribute("data-selected") == "1"

    page.locator(".awl-crumb-in button", has_text="while i < cycles:").click()
    settle(page, lambda: editor.selected == LOOP and attribute(block(page, LOOP), "data-selected") == "1")

    assert block(page, LOOP).get_attribute("data-selected") == "1"
    assert page.locator('.awl-block[data-selected="1"]').count() == 1, "and the one it left is no longer wearing it"

    # A crumb for a lane, which React Flow cannot select at all: the lane's own
    # view carries the ring for the same reason a block's does.
    block(page, THEN_FIRST).click()
    settle(page, lambda: editor.selected == THEN_FIRST)
    lane = node(page, THEN_LANE).locator(".awl-lane")
    page.locator(".awl-crumb-in button", has_text="then").click()
    settle(page, lambda: editor.selected == THEN_LANE and attribute(lane, "data-selected") == "1")
    assert lane.get_attribute("data-selected") == "1"


# -- a placed loop, and a bounded run ------------------------------------------


def test_a_loop_from_the_toolbox_reaches_the_canvas_as_while_false(page, live, shots):
    """It reaches the canvas before its condition does and the run button is one
    click away. ``while i < 10:`` dropped into a body that never touches ``i``
    took the whole process down and needed a restart.
    """
    editor = open_editor(page, live)
    assert page.locator('[data-tool="loop"]').get_attribute("title") == "while False:\n    pass"

    drag(page, page.locator('[data-tool="loop"]'), page.locator('[data-zone="body.7.body:5"]'))
    settle(page, lambda: "while False:" in editor.model.source)
    assert editor.error == "", editor.error
    still_runs(editor)

    placed = block(page, "body.7.body.5").locator(".awl-badge")
    started = time.time()
    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay) and bool(shown(placed)))
    assert time.time() - started < 30, "the run came back"
    assert "TimeoutError" not in (editor.error or ""), editor.error
    assert editor.status.startswith("ran procedure:"), editor.status
    badge = placed.text_content()
    assert badge and TIMES not in badge, f"the loop was reached and turned no times: {badge!r}"

    page.screenshot(path=str(shots / "17-bounded-run.png"))


def test_a_loop_edited_into_running_forever_is_stopped_and_reported(page, live):
    """The second half, because a template is not the only way to place one.

    ``run()`` takes a deadline and stops through the tracer, which is already on
    every line. What ran before the deadline is still reported, and the editor
    is still there afterwards.
    """
    editor = open_editor(page, live)
    drag(page, page.locator('[data-tool="loop"]'), page.locator('[data-zone="body.7.body:5"]'))
    settle(page, lambda: "while False:" in editor.model.source)

    retype(page, page.locator('[data-edit="body.7.body.5"]'), "True")
    page.keyboard.press("Enter")
    settle(page, lambda: "while True:" in editor.model.source)
    assert "while True:" in editor.model.source

    started = time.time()
    page.locator(".awl-run button").click()
    settle(page, lambda: "TimeoutError" in (editor.error or ""), timeout=40)
    elapsed = time.time() - started

    assert "TimeoutError" in editor.error, editor.error
    assert elapsed < 30, elapsed
    assert editor.overlay, "and what ran before the deadline is still reported"
    settle(page, lambda: shown(page.locator('[data-testid="status"]')).startswith("TimeoutError"))
    assert page.locator('[data-testid="status"]').text_content().startswith("TimeoutError")

    # Still an editor afterwards, which is the whole difference from a restart.
    retype(page, page.locator('[data-edit="body.7.body.2"]'), "i = 4")
    page.keyboard.press("Enter")
    settle(page, lambda: "i = 4" in editor.model.source)
    assert "i = 4" in editor.model.source


@pytest.mark.parametrize("kind", [kind for _group, items in prf.TOOLBOX for kind, _label, _code in items])
def test_every_toolbox_template_raises_at_worst_and_never_hangs(kind):
    """``rest(600)``, ``i += 1`` and ``if value > 0:`` all name things the scope
    they land in may not have, and dropped where it does not they raise
    ``NameError``: a line, a name, and one undo. That is accepted. The loop is
    the one that had to change, because a body that never reaches its condition
    raises nothing at all.
    """
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="procedure", entry="procedure", arguments=(1,))
    editor.command({"op": "insert", "into": "body.7.body", "index": 2, "kind": kind})
    assert editor.error == "", editor.error
    still_runs(editor)

    started = time.time()
    editor.command({"op": "run"})
    assert time.time() - started < 30, "it came back"
    assert "TimeoutError" not in (editor.error or ""), f"{kind} was still running when the deadline passed"
    assert editor.overlay, "and something was observed"


# -- reporting a failure as the failure it was ---------------------------------


def test_a_failure_inside_a_handler_is_not_reported_as_an_unknown_gesture(monkeypatch):
    """The lookup and the call were under one ``except AttributeError``, so any
    ``AttributeError`` raised anywhere inside a handler came back as
    ``unknown gesture 'move'`` and sent whoever read it looking for a gesture
    that is wired up perfectly well.
    """
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="procedure")

    def explode(_request):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr(editor, "_do_move", explode)
    editor.command({"op": "move", "path": "body.7.body.2", "into": "body.7.body", "index": 3})
    assert editor.error == "AttributeError: 'NoneType' object has no attribute 'get'"

    editor.command({"op": "genuinely_not_a_gesture"})
    assert editor.error == "unknown gesture 'genuinely_not_a_gesture'"


# -- what it costs -------------------------------------------------------------


# -- the source pane is an IDE -------------------------------------------------


def test_a_type_error_is_underlined_in_the_pane_with_tys_own_message(page, live, shots):
    """The failure this guards against is a Monaco that looks like an IDE and
    reports nothing, so the assertion is on all three of what ty said, what
    Monaco is holding, and what is drawn.

    The error is typed into a block on the canvas, not pasted into the pane:
    the point is that the two halves of the screen are one document, so an edit
    made on the canvas is checked in the pane.
    """
    editor = open_editor(page, live, ty=True)
    assert markers(page, "ty") == [], "the sample type-checks as it stands"
    assert editor.source_pane.checked == 0

    retype(page, page.locator(f'[data-edit="{CHARGE}"]'), 'peak = charge("not a ChargeParam")')
    page.keyboard.press("Enter")
    settle(page, lambda: "not a ChargeParam" in editor.model.source)
    settle(page, lambda: editor.source_pane.checked > 0, timeout=30)

    found = markers(page, "ty")
    assert found, "ty found nothing wrong with passing a string where a ChargeParam is declared"
    assert any("ChargeParam" in entry["message"] for entry in found), found
    assert any(entry["code"] == "invalid-argument-type" for entry in found), [entry["code"] for entry in found]

    spot(page, "not a ChargeParam")
    page.wait_for_timeout(400)
    squiggles = deep(page, ".squiggly-error")
    assert squiggles, "and the reader can see it, not only the marker registry"

    page.screenshot(path=str(shots / "18-diagnostic.png"))


def test_hovering_a_name_says_what_it_was_inferred_to_be(page, live, shots):
    """Two answers in one popup, and each is the only one that could give it.

    ty says ``peak`` is a ``float``, which is a fact about the program that no
    amount of reading this package's own graph would produce. AWL says ``charge``
    resolves to ``awl.ui.sample.charge``, which is the question this package
    exists to answer and which a type checker is never asked.
    """
    open_editor(page, live, ty=True)

    hover_source(page, "peak = charge", offset=1)
    settle(page, lambda: bool(deep(page, ".monaco-hover-content")), timeout=20)
    shown = [entry["text"] for entry in deep(page, ".monaco-hover-content") if (entry["text"] or "").strip()]
    assert shown, "nothing opened at all"
    assert any("float" in text for text in shown), shown

    page.screenshot(path=str(shots / "19-hover.png"))

    page.mouse.move(10, 400)
    page.wait_for_timeout(500)
    hover_source(page, "charge(ChargeParam", offset=1)
    settle(
        page, lambda: any("resolves to" in (e["text"] or "") for e in deep(page, ".monaco-hover-content")), timeout=20
    )
    resolved = [
        entry["text"] for entry in deep(page, ".monaco-hover-content") if "resolves to" in (entry["text"] or "")
    ]
    assert resolved, [entry["text"] for entry in deep(page, ".monaco-hover-content")]
    assert "awl.ui.sample.charge" in resolved[0], resolved


def test_completion_offers_a_member_only_a_type_checker_could_know(page, live, shots):
    """``param.`` inside ``charge`` offers ``target_voltage``.

    Nothing in the text says ``param`` has that attribute: it is declared on
    ``ChargeParam``, three functions away, and only the annotation on the
    parameter connects the two. A word-list completion cannot produce it.
    """
    editor = open_editor(page, live, ty=True)
    page.locator(f'[data-grip="{CHARGE}"]').dblclick()
    settle(page, lambda: editor.scope == "charge")

    where = spot(page, "voltage += param.c_rate")
    page.mouse.click(where["x"], where["y"])
    page.keyboard.press("End")
    page.keyboard.type("\nparam.")
    page.wait_for_timeout(2500)

    offered = [entry["text"] for entry in deep(page, ".suggest-widget .monaco-list-row")]
    assert offered, "the suggest widget never opened"
    assert any("target_voltage" in text for text in offered), offered[:12]
    assert any("c_rate" in text for text in offered), offered[:12]
    assert "target_voltage" in " ".join(offered[:4]), (
        f"and ty's own ranking is kept, so the list does not open on a dunder: {offered[:4]}"
    )

    page.screenshot(path=str(shots / "20-completion.png"))

    page.keyboard.press("Escape")
    page.keyboard.press("ControlOrMeta+z")
    page.keyboard.press("ControlOrMeta+z")


def test_the_last_run_is_written_into_the_source_pane_as_well(page, live, shots):
    """The overlay is joined by span, and the pane is the same document, so the
    two halves of the screen cannot disagree about which statement ran.

    Cleared with the rest of the overlay on the next edit, for the reason every
    other mark is: a decoration keyed on a line that has since moved names the
    wrong statement.
    """
    editor = open_editor(page, live)
    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay))

    spot(page, "while i < cycles")
    page.wait_for_timeout(400)
    written = [entry["text"] for entry in deep(page, ".awl-ran")]
    assert written, "the run wrote nothing into the pane"
    assert any(TIMES in text for text in written), written
    assert styled(page.locator(".awl-ran").first, "color") == {"color": "rgb(21, 128, 61)"}

    page.screenshot(path=str(shots / "24-source-overlay.png"))

    retype(page, page.locator('[data-edit="body.7.body.2"]'), "i = 5")
    page.keyboard.press("Enter")
    settle(page, lambda: "i = 5" in editor.model.source)
    assert deep(page, ".awl-ran") == [], "and it goes when the overlay does"


# -- the arrows ----------------------------------------------------------------


def _points(path: str) -> list[tuple[float, float]]:
    """Return every point of an SVG path, which for a step edge is its corners.

    Every command in one of these takes coordinates in pairs, so the numbers
    can be read in order: a quadratic's control point is the corner it rounds,
    which is exactly the point being asserted about.
    """
    import re

    numbers = [float(found) for found in re.findall(r"-?\d+(?:\.\d+)?", path)]
    return [(numbers[at], numbers[at + 1]) for at in range(0, len(numbers) - 1, 2)]


def test_two_stacked_blocks_are_joined_by_one_straight_vertical_line(page, live):
    """The connector used to be a flat Z three pixels tall.

    ``panel-reactflow`` declares every input handle ``Position.Left`` and every
    output ``Position.Right``, so React Flow left each block sideways and
    arrived at the next one sideways, and the twenty pixel default stub was the
    entire visible connector. With no stub the same path collapses to the two
    corners it needs, and between two blocks sharing a centre line that is one
    vertical drop.
    """
    editor = open_editor(page, live)

    drawn = page.locator('.react-flow__edge[data-id="body.7.body.1->body.7.body.2"] .react-flow__edge-path')
    path = drawn.get_attribute("d")
    points = _points(path)
    assert points, path
    assert "Q" not in path, f"a straight drop turns no corners: {path}"
    assert len({round(x, 1) for x, _y in points}) == 1, f"every point is on one vertical: {path}"

    # In the canvas's own coordinates, which is where the geometry is decided.
    # The rectangle on screen is the arrowhead's as well as the line's, and the
    # arrow is wider than the line it ends.
    top = editor.boxes["body.7.body.1"]
    bottom = editor.boxes["body.7.body.2"]
    assert points[0][0] == pytest.approx(top[0] + top[2] / 2, abs=1), "it leaves the middle of the block above"
    ys = sorted(y for _x, y in points)
    assert ys[0] >= top[1] + top[3] - 1, "from its bottom edge"
    assert ys[-1] <= bottom[1] + 1, "and arrives on the top of the one below"
    assert ys[-1] - ys[0] > 20, f"with room enough to be seen: {ys[-1] - ys[0]}"

    # Drawn, and drawn as a line: `is_visible` is not asked, because a path that
    # is exactly vertical has a zero width rectangle and Playwright reads that
    # as hidden, which is the one shape this test exists to produce.
    on_screen = drawn.bounding_box()
    assert on_screen["height"] > 10, on_screen
    assert styled(drawn, "strokeWidth", "stroke", "vectorEffect") == {
        "strokeWidth": "1.8px",
        "stroke": "rgb(100, 116, 139)",
        "vectorEffect": "non-scaling-stroke",
    }


def test_the_connector_between_two_blocks_is_a_line_that_joins_them(page, live, shots):
    """Measured where a reader looks, which the test beside this one does not.

    That one reads the ``d`` attribute, and ``d`` is written in the canvas's own
    coordinates: it is compared against ``editor.boxes``, which are the same
    coordinates, so it says the path has the right *shape* and nothing at all
    about what is drawn. Every connector on the level passed it while a reader
    called them "short stubs, not joins".

    What they were is a line 0.77 of a pixel wide. A stroke width is in canvas
    units and shrinks with the viewport, and the level opens fitted to the page,
    so the join between two blocks was a pale anti-aliased hairline with a three
    pixel speck on the end of it. The geometry was right the whole time.

    So this measures the rendered rectangles through locators, which pierce the
    shadow root the canvas lives in. ``page.evaluate`` does not, and
    ``document.querySelectorAll('.react-flow__edge-path')`` returns nothing at
    all from inside one, which is the shape of assertion that passes by
    measuring an empty set.
    """
    editor = open_editor(page, live)
    joins = [edge for edge in editor.flow.edges if edge["data"]["drawn"] == "flow"]
    assert len(joins) > 5

    for edge in joins:
        drawn = page.locator(f'.react-flow__edge[data-id="{edge["id"]}"] .react-flow__edge-path')
        line = drawn.bounding_box()
        source = node(page, edge["source"]).bounding_box()
        target = node(page, edge["target"]).bounding_box()
        assert line and source and target, edge["id"]

        # It joins. Leaves the bottom edge of the block above and reaches the
        # top edge of the block below, rather than floating between the two.
        bottom = source["y"] + source["height"]
        assert -4 <= line["y"] - bottom <= 2, f"{edge['id']} starts {line['y'] - bottom:.1f} px off the block it leaves"
        # Short of the block by the head's clearance, deliberately: the
        # arrowhead's point sits on the path's last vertex, so a line that
        # reached the block put its tip underneath it.
        reach = target["y"] - line["y"] - line["height"]
        assert reach <= layout.GEOMETRY["head_clearance"] + 2, (
            f"{edge['id']} stops {reach:.1f} px short of the block it points at"
        )

        # And it runs down the middle of both, which is the other half of what
        # "a tick mark beside the flow" means.
        for name, box in (("source", source), ("target", target)):
            middle = box["x"] + box["width"] / 2
            assert abs(line["x"] + line["width"] / 2 - middle) <= 2.5, (
                f"{edge['id']} is {line['x'] + line['width'] / 2 - middle:.1f} px off the {name}'s centre"
            )

        # The arrowhead is wide enough to be seen at the zoom the level opens
        # at, and narrow enough that it is not the whole connector.
        assert line["width"] >= 4.5, f"{edge['id']}'s arrowhead is {line['width']:.1f} px across"
        assert line["width"] <= (target["y"] - bottom) / 2, "and it does not swallow the line it ends"

    # The line itself, in the property that decides whether it is one. A stroke
    # in canvas units is what made it half a pixel; this one is not.
    first = page.locator(f'.react-flow__edge[data-id="{joins[0]["id"]}"] .react-flow__edge-path')
    assert styled(first, "vectorEffect", "stroke", "strokeWidth") == {
        "vectorEffect": "non-scaling-stroke",
        "stroke": "rgb(100, 116, 139)",
        "strokeWidth": "1.8px",
    }

    top = node(page, "body.7.body.0").bounding_box()
    page.screenshot(
        path=str(shots / "34-join.png"),
        clip={"x": top["x"] - 6, "y": top["y"] - 6, "width": min(520, top["width"] + 12), "height": 120},
    )


def test_every_arrow_on_the_canvas_arrives_pointing_down_the_line_it_came_along(page, live, shots):
    """The arrowhead used to hook in sideways at the top of the block it reached.

    Asserted on the path's ``d``, which is the *shape* of the path in the
    canvas's own coordinates and is not what a reader sees: the rendered
    rectangles are
    :func:`test_the_connector_between_two_blocks_is_a_line_that_joins_them`'s.

    ``panel-reactflow`` declares every input handle ``Position.Left`` and every
    output ``Position.Right``, and React Flow runs a step path's vertical leg
    half way between the two anchors and takes no argument about where: two
    anchors on one vertical give a straight drop and a downward arrowhead, and
    two at different indents give a path that ends in a sideways stub across the
    top of the target. Every edge out of a lane was one of those, because a
    block inside a lane is inset from whatever follows the container.

    So the edge is drawn from the container instead, which stands in the same
    lane as its target. Asserted on every edge the level draws, not on one:
    the last two segments of each path share an x, which is what makes the
    arrowhead point down the line it travelled.
    """
    editor = open_editor(page, live)
    drawn = page.locator(".react-flow__edge-path")
    assert drawn.count() == len(editor.flow.edges) > 5

    for index in range(drawn.count()):
        path = drawn.nth(index).get_attribute("d")
        points = _points(path)
        assert points[-1][0] == pytest.approx(points[-2][0], abs=0.5), (
            f"the last segment of {path} is sideways, so the arrowhead is across the top of the block"
        )
        edge = editor.flow.edges[index]
        source = editor.boxes[edge["source"]]
        target = editor.boxes[edge["target"]]
        assert points[0][0] == pytest.approx(source[0] + source[2] / 2, abs=1), "it leaves the middle of its block"
        assert points[-1][0] == pytest.approx(target[0] + target[2] / 2, abs=1), "and arrives at the middle of the next"
        assert points[-1][1] == pytest.approx(target[1] - layout.GEOMETRY["head_clearance"], abs=1), (
            "clear of its top edge, so the arrowhead is not painted over by the block"
        )

    # The one that used to be worst: out of the branch, over two borders.
    leaves = page.locator(f'.react-flow__edge[data-id="{BRANCH}->body.7.body.3.body.2"] .react-flow__edge-path')
    assert "Q" not in leaves.get_attribute("d"), leaves.get_attribute("d")
    assert leaves.bounding_box()["height"] > 8, "and it is drawn, which the rectangles beside this one measure"

    zoom_onto(page, LOOP, turns=2)
    page.screenshot(path=str(shots / "21-edges.png"))


def test_a_branch_rejoins_below_the_container_and_says_which_lane_is_the_false_one(page, live, shots):
    """``then`` ends, the container ends, and control lands on the statement
    after it, on one line drawn once.

    The label is the other half. The plan sends ``when_false`` out of an ``if``
    with no ``else`` to whatever follows it, which is true of the source and
    wrong on a canvas that draws an ``else`` column anyway: the reader sees an
    empty lane beside the ``then`` and an arrow labelled ``when_false`` pointing
    past both of them. The empty lane *is* the false path, so it carries the
    word, and the connector out of the container carries none: it stands for
    two of the plan's edges now and naming one of them would name the wrong one.
    """
    editor = open_editor(page, live)

    assert editor.lane_kinds[ELSE_LANE] == "when_false"
    assert node(page, ELSE_LANE).locator(".awl-lane-kind").text_content() == "when_false"
    assert node(page, ELSE_LANE).locator(".awl-lane-kind").is_visible()

    drawn = page.locator(f'.react-flow__edge[data-id="{BRANCH}->body.7.body.3.body.2"]')
    assert drawn.locator(".react-flow__edge-text").count() == 0, "the connector out of the branch says nothing"
    assert page.locator(".react-flow__edge-text", has_text="when_false").count() == 1, (
        "and the one `when_false` left on the canvas is the loop's own exit"
    )

    points = _points(drawn.locator(".react-flow__edge-path").get_attribute("d"))
    leaving = editor.boxes[BRANCH]
    after = editor.boxes["body.7.body.3.body.2"]
    assert points[0] == pytest.approx((leaving[0] + leaving[2] / 2, leaving[1] + leaving[3]), abs=1), (
        "it leaves the bottom of the container"
    )
    assert points[-1] == pytest.approx(
        (after[0] + after[2] / 2, after[1] - layout.GEOMETRY["head_clearance"]), abs=1
    ), "and arrives just clear of the statement after it, so its arrowhead is visible"

    zoom_onto(page, BRANCH, turns=3)
    page.screenshot(path=str(shots / "25-when-false.png"))


# -- the form is inside the node, and lines up with it -------------------------


def test_the_fields_line_up_with_the_node_they_are_inside(page, live, shots):
    """The claim this variant is built on is that the form lives *inside* the
    node, so where it sits inside it is the claim.

    Measured against the node's rectangle and against the header above it, not
    looked at: the two used hand-tuned paddings in separate shadow roots, which
    put them three pixels apart and let the second field run past the node's
    right edge. Both assertions passed on class names throughout.
    """
    # A different node from the one 02-form is taken of, and a different pair of
    # widgets: `Report(cycles=0, peak_voltage=0.0)` is an int beside a float.
    open_editor(page, live)
    holder = node(page, "body.7.body.1")
    zoom_onto(page, "body.7.body.1", turns=3)

    box = holder.bounding_box()
    fields = holder.locator(".awl-field input")
    assert fields.count() == 2

    chip = holder.locator("[data-grip]").bounding_box()
    text = holder.locator("[data-edit]").bounding_box()
    boxes = [fields.nth(index).bounding_box() for index in range(2)]

    for index, field in enumerate(boxes):
        assert inside(box, field, slack=1.0), f"field {index} is inside the node's rectangle"

    left = chip["x"] - box["x"]
    assert abs((boxes[0]["x"] - box["x"]) - left) < 1.5, (
        f"the first field starts where the header does: {boxes[0]['x'] - box['x']} against {left}"
    )
    right = (box["x"] + box["width"]) - (boxes[-1]["x"] + boxes[-1]["width"])
    assert abs(right - left) < 1.5, f"and the last one ends the same distance from the other edge: {right}"

    assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1.0, "the two sit on one line"
    assert abs(boxes[0]["height"] - boxes[1]["height"]) < 1.0, "at one height"
    assert abs(boxes[0]["width"] - boxes[1]["width"]) < 1.5, "and share the room evenly"
    assert boxes[1]["x"] > boxes[0]["x"] + boxes[0]["width"], "side by side and not stacked"

    # And the header's own input is inside too, which is what says the whole
    # block is one column rather than a row that happens to be near a form.
    assert text["x"] > box["x"] and text["x"] + text["width"] <= box["x"] + box["width"] + 1

    # The rules really reached the widget. Each field is a Panel widget in a
    # shadow root of its own, and a stylesheet handed to one of those is the
    # thing this comparison has already had reach nothing at all while every
    # class-name assertion passed.
    painted = styled(fields.nth(0), "fontFamily", "boxSizing")
    assert "monospace" in painted["fontFamily"], painted
    assert painted["boxSizing"] == "border-box", "without which the second field runs past the node"
    label = styled(holder.locator(".awl-field label").first, "fontSize", "textOverflow")
    assert label == {"fontSize": "9px", "textOverflow": "ellipsis"}, label

    page.screenshot(path=str(shots / "22-fields-aligned.png"))


def test_selecting_a_block_scrolls_the_pane_to_the_line_it_covers(page, live):
    """Opening at the top of the file shows the module docstring at every level,
    which reads as broken highlighting when it is one long string token.

    The pane scrolls to the statement, so the two halves of the screen are
    looking at the same thing. Asserted on Monaco's own visible range rather
    than on a scroll offset: a line number is what the requirement is about.
    """
    open_editor(page, live)

    def visible() -> tuple[int, int]:
        seen = page.evaluate(
            "() => { const r = monaco.editor.getEditors()[0].getVisibleRanges()[0];"
            " return [r.startLineNumber, r.endLineNumber] }"
        )
        return (seen[0], seen[1])

    assert visible()[0] <= 2, "it opens at the top of the file"

    block(page, LAST_IN_LOOP).click()
    settle(page, lambda: visible()[0] > 2)
    first, last = visible()
    at = page.evaluate(
        "() => { const text = monaco.editor.getEditors()[0].getModel();"
        " for (let line = 1; line <= text.getLineCount(); line++)"
        "  if (text.getLineContent(line).trim() === 'i += 1') return line; return 0 }"
    )
    assert at > 0
    assert first <= at <= last, f"line {at} is on screen, between {first} and {last}"


def test_every_block_in_a_lane_shares_its_left_and_right_edge(page, live):
    """A column of blocks reads as a column, and that is also what makes the
    back edge computable: a lane with one right edge puts half way between a
    block and its container inside the gutter.
    """
    editor = open_editor(page, live)
    inner = [CHARGE, BRANCH, "body.7.body.3.body.2", LAST_IN_LOOP]
    lefts = {round(editor.boxes[path][0]) for path in inner}
    rights = {round(editor.boxes[path][0] + editor.boxes[path][2]) for path in inner}
    assert len(lefts) == 1, lefts
    assert len(rights) == 1, rights

    drawn = [node(page, path).bounding_box() for path in inner]
    assert len({round(box["x"]) for box in drawn}) == 1, drawn
    assert len({round(box["x"] + box["width"]) for box in drawn}) == 1, drawn


# -- comments round trip -------------------------------------------------------


def test_a_comment_beside_a_statement_is_the_blocks_explanation(page, live, shots):
    """``ast`` has no comment node, so the compact document has none either and
    a note is read off the source the block covers.

    What is asserted is the round trip: a comment typed into the file appears on
    the block, one edited on the block appears in the file, and the file is
    patched by span throughout, which is the only path on which a comment
    survives at all.
    """
    editor = open_editor(page, live)
    assert page.locator('[data-note="body.7.body.2"]').input_value() == "", "nothing is written there yet"

    # Into the file first, through the pane, so the reading direction is tested
    # against something the canvas did not write.
    where = spot(page, "i = 0")
    page.mouse.click(where["x"], where["y"])
    page.keyboard.press("End")
    page.keyboard.type("  # the cycle counter")
    settle(page, lambda: "the cycle counter" in editor.model.source)

    assert editor.error == "", editor.error
    note = page.locator('[data-note="body.7.body.2"]')
    settle(page, lambda: note.input_value() == "the cycle counter")
    assert note.input_value() == "the cycle counter", "the block says what the comment says"
    assert editor._blocks["body.7.body.2"].note_where == "beside"

    zoom_onto(page, "body.7.body.2", turns=3)
    assert page.locator('[data-note="body.7.body.2"]').input_value() == "the cycle counter"
    page.screenshot(path=str(shots / "23-note.png"))

    # And back out again, from the block into the file.
    retype(page, note, "counts the cycles")
    page.keyboard.press("Enter")
    settle(page, lambda: "counts the cycles" in editor.model.source)

    assert editor.error == "", editor.error
    assert "    i = 0  # counts the cycles" in editor.model.source, editor.model.source
    assert not editor.model.reformats(), "written by span, which is the only way a comment survives"
    assert source_text(page) == editor.model.source, "and the pane holds what the file now says"
    still_runs(editor)


def test_a_comment_written_on_its_own_line_is_a_note_and_not_a_block(page, live, shots):
    """A comment is trivia. It belongs to a statement and is never one.

    Typed into the file on a line of its own, at the statement's own
    indentation, it has to come back as that statement's note with
    ``where="above"``, and nothing on the canvas may appear for it: a block for
    a comment is a block for something that does not run, in a canvas whose
    whole claim is that it draws what runs.

    Asserted both ways round. The note field under the statement says it, and no
    block anywhere on the level is carrying the comment's text.
    """
    editor = open_editor(page, live)
    drawn = page.locator(".react-flow__node").count()

    where = spot(page, "i = 0")
    page.mouse.click(where["x"], where["y"])
    page.keyboard.press("Home")
    page.keyboard.type("# the cycle counter\n")
    settle(page, lambda: "# the cycle counter" in editor.model.source)

    assert editor.error == "", editor.error
    assert "    # the cycle counter\n    i = 0\n" in editor.model.source, editor.model.source

    note = page.locator('[data-note="body.7.body.2"]')
    settle(page, lambda: note.input_value() == "the cycle counter")
    assert note.input_value() == "the cycle counter", "the statement under it carries it"
    assert editor._blocks["body.7.body.2"].note_where == "above"
    assert page.locator('[data-note="body.7.body.2"]').count() == 1

    assert page.locator(".react-flow__node").count() == drawn, "and no node appeared for it"
    labels = [block.label for block in tree.walk(editor.tree)]
    assert not any("cycle counter" in label for label in labels), labels
    assert not any("#" in label for label in labels), labels

    zoom_onto(page, "body.7.body.2", turns=3)
    assert page.locator('[data-note="body.7.body.2"]').input_value() == "the cycle counter"
    assert page.locator('.awl-notes[data-where="above"]').count() >= 1
    page.screenshot(path=str(shots / "26-note-above.png"))

    # And it round trips from the block back into the file, still on its own
    # line, because that is where the reader put it.
    retype(page, note, "counts the cycles")
    page.keyboard.press("Enter")
    settle(page, lambda: "counts the cycles" in editor.model.source)
    assert "    # counts the cycles\n    i = 0\n" in editor.model.source, editor.model.source
    assert not editor.model.reformats()
    still_runs(editor)


def test_the_note_a_block_offers_is_the_models_and_not_a_copy_of_its_rules():
    """The canvas had its own comment reader and the two answers drifted.

    The rule that broke is the one about where a first note goes: the end of the
    statement is not the end of its first line. A module docstring's first line
    ends *inside the literal*, and a note appended there changed what the string
    said while reporting success and leaving ``reformats()`` false.

    :meth:`~awl.ui.EditorModel.trivia` and :meth:`~awl.ui.EditorModel.set_trivia`
    have the rule, are cross-checked against the document's own comment layer in
    ``tests/test_pipeline.py``, and are what this canvas now calls.
    """
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="")
    docstring = editor._blocks["body.0"]
    assert docstring.span is not None and docstring.span[0] != docstring.span[2], "it really does span its lines"
    assert docstring.note_span == editor.model.trivia(docstring.span)["span"], "read through the model"

    editor.command({"op": "note", "path": "body.0", "text": "about the module"})
    assert editor.error == "", editor.error

    lines = editor.model.source.splitlines()
    assert lines[docstring.span[2] - 1] == '"""  # about the module', lines[docstring.span[2] - 1]
    assert lines[0] == '"""The procedure the editor opens on, written to be edited and to be run.', lines[0]
    assert not editor.model.reformats()
    still_runs(editor)
    assert ui.open_sample().document["body"][0]["literal"] == editor.model.document["body"][0]["literal"], (
        "and the docstring still says what it said"
    )


def test_a_comment_on_the_line_above_belongs_to_the_statement_under_it():
    """The other of the two places a note is read from, and the limit that comes
    with it.

    Only the line immediately above, and never a run of them: this cannot tell a
    banner from commented-out code, so claiming four lines as one statement's
    explanation would put dead code in a field that writes it back as prose. A
    run keeps its lines as trivia and the nearest one is the note.
    """
    model = ui.load(
        "def procedure():\n"
        "    # a banner about the whole block\n"
        "    # start from nothing\n"
        "    total = 0\n"
        "    return total\n",
        module="m",
        file="m.py",
    )
    editor = prf.PanelReactFlowEditor(model, scope="procedure")
    found = {block.id: (block.note, block.note_where) for block in tree.walk(editor.tree)}

    assert found["body.0.body.0"] == ("start from nothing", "above"), found
    assert found["body.0.body.1"] == ("", ""), "and the return, which has no comment, offers an empty one"

    editor.command({"op": "note", "path": "body.0.body.0", "text": "start from zero"})
    assert editor.error == "", editor.error
    assert "    # start from zero\n    total = 0\n" in editor.model.source, editor.model.source
    assert "# a banner about the whole block" in editor.model.source, "the line above it was not touched"
    assert not editor.model.reformats()
    still_runs(editor)

    # Cleared, which takes the line with it rather than leaving a bare `#`.
    editor.command({"op": "note", "path": "body.0.body.0", "text": ""})
    assert editor.status == "note removed", editor.status
    assert "start from zero" not in editor.model.source
    assert "# a banner about the whole block\n    total = 0\n" in editor.model.source, editor.model.source


def test_a_note_written_on_a_block_that_had_none_lands_beside_it():
    """The first comment on a statement has no span to replace, so it is written
    into a zero width one at the end of the statement's own line.

    Still the span path: ``replace_at`` over an empty range is an insertion, and
    an insertion splices exactly like a replacement. The structural path would
    regenerate the module and drop every comment in it, including this one.
    """
    editor = prf.PanelReactFlowEditor(ui.open_sample(), scope="procedure")
    editor.command({"op": "note", "path": LAST_IN_LOOP, "text": "one cycle done"})

    assert editor.error == "", editor.error
    assert "        i += 1  # one cycle done\n" in editor.model.source, editor.model.source
    assert not editor.model.reformats(), "so nothing else in the file was rewritten"
    still_runs(editor)

    assert editor._blocks[LAST_IN_LOOP].note == "one cycle done"
    assert editor._blocks[LAST_IN_LOOP].note_where == "beside"


def test_a_structural_edit_still_says_the_comments_are_going(page, live):
    """The warning matters more now that comments are editable.

    A note is a span patch and costs the file nothing. An insert regenerates the
    module and takes every comment in it, so a reader who has just written one
    has to be told before it happens rather than after.
    """
    editor = open_editor(page, live)
    editor.command({"op": "note", "path": "body.7.body.2", "text": "the cycle counter"})
    settle(page, lambda: "the cycle counter" in editor.model.source)
    assert not editor.model.reformats()

    warning = page.locator('[data-testid="reformats"]')
    drag(page, page.locator('[data-tool="call"]'), page.locator('[data-zone="body.7.body:5"]'))
    settle(page, lambda: editor.status == "added")

    assert editor.status == "added", editor.error
    assert warning.count() == 1, "the editor said the file was rewritten"
    assert "the cycle counter" not in editor.model.source, (
        "and it really was: the comment is gone, which is what the warning is about"
    )
    still_runs(editor)


# -- the shell: a console, a grip, and an icon font ----------------------------


def test_the_canvas_fills_the_page_down_to_the_console(page, live, shots):
    """211 pixels of empty page between the canvas and the console.

    The canvas had a fixed height and the source pane beside it stretched, so
    the two columns ended in different places and the console sat below the
    taller one with nothing in between. It also cost the canvas the zoom the
    level opens at, because that is fitted to the canvas: a level 1402 units
    tall drawn into 556 pixels is 0.34, and every connector on it is a third
    shorter than it needs to be for the same reason.

    Asserted as rectangles, so a layout change cannot reopen the gap quietly.
    """
    editor = open_editor(page, live)

    canvas = page.locator('[data-testid="rf__wrapper"]').bounding_box()
    pane = page.locator(".awl-pane").bounding_box()
    console = page.locator(".awl-bottom").bounding_box()
    side = page.locator(".awl-side").bounding_box()

    assert abs(canvas["y"] + canvas["height"] - console["y"]) <= 3, (
        f"{console['y'] - canvas['y'] - canvas['height']:.0f} px of page between the canvas and the console"
    )
    assert abs(canvas["height"] - pane["height"]) <= 2, "the two columns are the same height"
    assert abs(side["height"] - pane["height"]) <= 2, "and so is the toolbox"
    assert abs(console["y"] + console["height"] - VIEWPORT["height"]) <= 2, "the console reaches the bottom of the page"
    assert console["width"] == pytest.approx(VIEWPORT["width"], abs=2), "and across it"
    assert canvas["height"] > VIEWPORT["height"] * 0.6, canvas

    # The zoom it bought, which is what the connectors are drawn at.
    assert editor.flow.viewport["zoom"] > 0.37, editor.flow.viewport
    assert node(page, "body.7.body.0").bounding_box()["height"] > 20, "and the blocks are drawn at a readable size"

    # The boundary itself, across the page, which is where the empty band was.
    # A whole-page shot here is "01-level" under a second name, and two of those
    # is the duplicate this file hashes for.
    page.screenshot(
        path=str(shots / "35-shell.png"),
        clip={"x": 0, "y": console["y"] - 110, "width": VIEWPORT["width"], "height": 190},
    )


def test_the_console_holds_the_run_its_output_and_what_the_trace_said(page, live, shots):
    """The bottom of the screen was empty and the notice was one line long.

    A run produces three things and a line can hold one of them, so two were
    dropped every time: whatever the procedure printed went to the terminal the
    server was started from, which a reader of the page does not have, and the
    per-step counts existed only as badges scattered over the canvas.

    Asserted against the same overlay the badges are drawn from, so the two
    halves of the screen cannot disagree, and against the computed colour of an
    error line, because a failure that reads like a notice is a failure nobody
    sees.
    """
    editor = open_editor(page, live)
    console = page.locator('[data-testid="console"]')

    box = console.bounding_box()
    canvas = page.locator('[data-testid="rf__wrapper"]').bounding_box()
    assert box["y"] > canvas["y"] + canvas["height"] - 2, "it is under the canvas, in the room that was empty"
    assert box["width"] > VIEWPORT["width"] * 0.9, "and across the page"
    assert box["height"] > 80, box

    # Something to print, typed into the block the way anything else is. Not
    # the increment: a loop whose counter stops moving runs until the deadline
    # and fills the console with one line.
    printing = "body.7.body.3.body.2"
    retype(page, page.locator(f'[data-edit="{printing}"]'), "print('cycle', i)")
    page.keyboard.press("Enter")
    settle(page, lambda: "print('cycle', i)" in editor.model.source)

    page.locator(".awl-run button").click()
    settle(page, lambda: bool(editor.overlay) and "cycle 2" in shown(console))

    said = console.locator(".awl-line").all_text_contents()
    assert said[0] == "procedure(3)", said[:3]
    assert said[1:4] == ["cycle 0", "cycle 1", "cycle 2"], f"what the procedure printed: {said}"
    assert "ran procedure: 10/11 steps in procedure executed" in said, said
    assert "while i < cycles:  T+F" in said, said
    assert f"print('cycle', i)  {TIMES}3" in said, said

    # The same numbers the canvas is wearing, from the same overlay.
    for path, record in editor.overlay.items():
        badge, _state = editor.badge(editor._blocks[path])
        if badge:
            assert any(line.endswith(badge) for line in said), (path, record, badge)

    page.screenshot(path=str(shots / "31-console.png"))

    # And a failure, in the colour a failure is drawn in.
    page.locator(f'[data-delete="{THEN_FIRST}"]').click()
    settle(page, lambda: "pass" in editor.model.source)
    drag(page, page.locator('[data-grip="body.7.body.1"]'), page.locator('[data-zone="body.7.body:0"]'))
    settle(page, lambda: bool(editor.error))

    failed = console.locator('.awl-line[data-kind="error"]').last
    assert "docstring" in failed.text_content(), console.locator(".awl-line").all_text_contents()
    assert styled(failed, "color", "fontWeight") == {"color": "rgb(185, 28, 28)", "fontWeight": "600"}
    still_runs(editor)


def test_the_source_pane_takes_the_larger_share_and_a_grip_moves_the_boundary(page, live, shots):
    """420 px of 1280 is a viewer, not a pane you write in.

    The split is also a guess about which half the reader is working in, and the
    guess is wrong for half of what an editor is for, so the boundary is a grip.
    Measured on the rectangles either side of it: the pane grows by what the
    pointer moved, the canvas gives up the same, and the grip is still between
    them afterwards.
    """
    open_editor(page, live)

    grip = page.locator('[data-testid="splitter"]')
    pane = page.locator(".awl-pane")
    canvas = page.locator('[data-testid="rf__wrapper"]')

    started = pane.bounding_box()
    assert started["width"] > VIEWPORT["width"] * 0.4, f"the pane opens with a real share of the page: {started}"
    assert styled(grip, "cursor", "width") == {"cursor": "col-resize", "width": "7px"}

    at = grip.bounding_box()
    assert abs(at["x"] + at["width"] - started["x"]) < 2, "the grip is against the pane"
    was = canvas.bounding_box()

    page.mouse.move(at["x"] + at["width"] / 2, at["y"] + at["height"] / 2)
    page.mouse.down()
    for step in range(1, 9):
        page.mouse.move(at["x"] + at["width"] / 2 - 160 * step / 8, at["y"] + at["height"] / 2)
        page.wait_for_timeout(40)
    page.mouse.up()
    settle(page, lambda: (pane.bounding_box() or {}).get("width", 0) > started["width"] + 100)

    grown = pane.bounding_box()
    assert grown["width"] == pytest.approx(started["width"] + 160, abs=12), (started, grown)
    assert canvas.bounding_box()["width"] == pytest.approx(was["width"] - 160, abs=12), "the canvas gave up the room"
    moved = grip.bounding_box()
    assert abs(moved["x"] + moved["width"] - grown["x"]) < 2, "and the grip came with it"
    assert source_text(page), "the pane is still an editor afterwards"

    page.screenshot(path=str(shots / "29-splitter.png"))


def test_monacos_own_icon_font_is_loaded_and_the_icons_are_glyphs(page, live, shots):
    """Every icon in the pane was the notdef box.

    Monaco's own rule is ``src: url("./codicon.ttf")``, relative to the
    document, and the document is a Panel application served from ``/``: the
    browser asked this server for ``/codicon.ttf`` and got a 404. The rule also
    lives in a style element that never says ``monaco-editor``, so the copy this
    pane makes into its shadow root skipped it and the icons inherited the
    editor's monospace family instead.

    Both halves are asserted, because either one alone still draws a box: the
    font is registered and loaded, and an icon element is actually using it.
    One face and not two, because ``document.fonts.load`` loads every face of a
    family and a second rule left beside the broken one is still a broken one.
    """
    open_editor(page, live)

    faces = page.evaluate("() => [...document.fonts].map(face => [face.family, face.status])")
    assert [family for family, _status in faces].count("codicon") == 1, faces
    loaded = page.evaluate(
        "async () => { await document.fonts.load('16px codicon'); return document.fonts.check('16px codicon') }"
    )
    assert loaded, f"the font never arrived: {faces}"

    icons = deep(page, ".codicon")
    assert icons, "Monaco drew no icon at all, so this proves nothing either way"
    assert all("codicon" in entry["font"] for entry in icons[:4]), [entry["font"] for entry in icons[:4]]

    # A glyph and not a box. The notdef box is square; a codicon at 16 px is
    # drawn from the font's own advance, and the two differ.
    drawn = page.evaluate(
        """() => {
          const scratch = document.createElement('canvas').getContext('2d')
          scratch.font = '16px codicon'
          const glyph = scratch.measureText('\\uea76').width
          scratch.font = '16px monospace'
          return [glyph, scratch.measureText('\\uea76').width]
        }"""
    )
    assert drawn[0] != drawn[1], f"the icon is being drawn by the fallback family: {drawn}"

    # Shown, in the widget a reader meets them in.
    page.keyboard.press("Escape")
    click_source(page, 0.3)
    page.keyboard.press("ControlOrMeta+f")
    page.wait_for_timeout(600)
    assert deep(page, ".find-widget .codicon"), "the find widget did not open"
    page.screenshot(path=str(shots / "30-codicons.png"))
    page.keyboard.press("Escape")


def test_typing_speaks_to_python_once_the_typing_stops(page, live):
    """It synced the canvas on every keystroke, by two different routes.

    The round trip was debounced and the type check was not, and the check wrote
    its count back through a synced parameter: one whole-module check and one
    message to the server per character, which is what made the canvas the
    slowest thing on the page.

    Counted on the server, because that is where a round trip lands.
    """
    editor = open_editor(page, live)
    seen: list[str] = []
    original = editor.command

    def counting(request):
        seen.append(str(request.get("op")))
        return original(request)

    editor.command = counting
    editor.source_pane.on_command = counting
    try:
        where = spot(page, "i += 1")
        page.mouse.click(where["x"], where["y"])
        page.keyboard.press("End")
        page.keyboard.type("  # eight characters and more", delay=12)
        page.wait_for_timeout(60)
        assert seen.count("source") == 0, f"nothing is sent while the typing is still going: {seen}"

        settle(page, lambda: seen.count("source") == 1)
        assert seen.count("source") == 1, f"one round trip for the whole word, not one per letter: {seen}"
        assert "eight characters and more" in editor.model.source
    finally:
        editor.command = original
        editor.source_pane.on_command = original


def test_a_lane_label_clears_the_note_line_of_the_container_it_is_in(page, live, shots):
    """``THEN`` sat on top of the ``# note`` field of the ``if`` above it.

    A container's lanes start under its header, and the header was measured as a
    fixed 42 pixels while every block that can carry a comment is 22 pixels
    taller than that. Measured as rectangles: the lane's label is below the
    container's note line, and the note line is still inside the container.
    """
    editor = open_editor(page, live)

    for container, lanes in ((BRANCH, (THEN_LANE, ELSE_LANE)), (LOOP, (LOOP_LANE,))):
        note = page.locator(f'[data-path="{container}"] .awl-notes')
        assert note.count() == 1, container
        above = note.bounding_box()
        assert inside(node(page, container).bounding_box(), above, slack=3), f"{container} keeps its note inside it"
        for lane in lanes:
            label = node(page, lane).locator(".awl-lane").bounding_box()
            assert label["y"] >= above["y"] + above["height"] - 1, (
                f"{lane}'s label starts at {label['y']}, over the note line ending at {above['y'] + above['height']}"
            )

    # In the model's own coordinates too, where the number was wrong.
    branch = editor.boxes[BRANCH]
    then = editor.boxes[THEN_LANE]
    assert then[1] - branch[1] >= layout.block_height(editor._blocks[BRANCH]), (branch, then)

    zoom_onto(page, BRANCH, turns=4)
    assert page.locator(f'[data-path="{BRANCH}"] .awl-note').is_visible()
    page.screenshot(path=str(shots / "32-lane-label.png"))


def test_the_ring_wraps_the_whole_node_and_not_only_its_header(page, live, shots):
    """A block with typed values is a header above a form, in a column.

    The ring was painted on the header, which is one child of that column, so a
    node carrying two ``FloatInput``\\ s showed an outline around its top strip
    and nothing around the fields under it. On a block with no fields the header
    *is* the node, which is why this survived a test that asserted the computed
    outline.

    Asserted on a node that has fields, against the node's own rectangle.
    """
    open_editor(page, live)

    holder = node(page, CHARGE)
    assert holder.locator(".awl-field input").count() == 2, "this is the case that fails"

    block(page, CHARGE).click()
    settle(page, lambda: attribute(block(page, CHARGE), "data-selected") == "1")

    ringed = page.locator(".react-flow__node[data-awl-selected]")
    assert ringed.count() == 1, "one ring on the page"
    assert ringed.get_attribute("data-id") == CHARGE

    outline = styled(ringed, "outlineStyle", "outlineWidth", "outlineColor")
    assert outline["outlineStyle"] == "solid", outline
    assert float(outline["outlineWidth"].rstrip("px")) >= 2, outline

    drawn = ringed.bounding_box()
    box = holder.bounding_box()
    for key in ("x", "y", "width", "height"):
        assert drawn[key] == pytest.approx(box[key], abs=2), (key, drawn, box)

    fields = holder.locator(".awl-field input")
    for index in range(2):
        assert inside(drawn, fields.nth(index).bounding_box(), slack=3), (
            f"field {index} is inside the ring, not below it"
        )

    zoom_onto(page, CHARGE, turns=2)
    page.screenshot(path=str(shots / "33-ring.png"))


def test_what_the_page_costs_over_the_wire(page, live, shots):
    """Wire, decoded and request count, measured after the page settles.

    **This number is not comparable like-for-like with the other four.** They
    load ES modules from a CDN with no bundler, one request per module; this is
    a pip-installed wheel whose JavaScript is already built, served by the
    application's own server together with Panel's and Bokeh's runtimes. The
    request count in particular measures a different thing: 269 for React Flow
    with RJSF is a bundling failure, and a small count here is a wheel, not a
    virtue of this canvas.

    **This page is now by far the heaviest of the five, and deliberately.** The
    source pane is Monaco, which arrives from a CDN, and ty is Astral's type
    checker as 17.7 MB of WebAssembly. Nothing about that is free and nothing
    here rounds it off: the two are reported separately from the application's
    own bytes, so a reader can price the IDE features against the editor.

    Three figures, because they answer three questions. Wire is what the reader
    waits for. Decoded is what the browser then parses. The third is what the
    same bodies weigh gzipped, and it is here because Bokeh's own server
    compresses only some of what it serves: most of the weight is JavaScript
    that arrives whole and that any reverse proxy would have compressed. A
    number measured against a development server and compared with numbers
    measured against a CDN would be flattering to the CDN for a reason that has
    nothing to do with either canvas.
    """
    seen: list[Any] = []
    page.on("response", lambda response: seen.append(response))
    # No cache, because a measurement taken through one measures the cache.
    open_editor(page, live, cache=False, ty=True)
    page.wait_for_timeout(2500)

    rows: list[dict[str, Any]] = []
    for response in seen:
        row: dict[str, Any] = {"url": response.url, "wire": 0, "decoded": 0, "gzipped": 0, "body_read": False}
        # A response with no retrievable body is not a failure; a redirect has
        # none and still counts as a round trip.
        with contextlib.suppress(Exception):
            row["wire"] = response.request.sizes()["responseBodySize"]
        with contextlib.suppress(Exception):
            body = response.body()
            row["decoded"] = len(body)
            row["gzipped"] = len(gzip.compress(body, 6))
            row["body_read"] = True
        rows.append(row)

    # A streamed WebAssembly module hands back no body afterwards, and a total
    # that silently omitted 17.7 MB of it would be the same defect the spec
    # names for summing inside `page.on("response")`: a number that is quietly
    # short. What could not be read is listed rather than rounded away.
    unread = [row["url"] for row in rows if not row["body_read"] and row["wire"]]

    def part(rows: list[dict[str, Any]], key: str) -> int:
        return sum(row[key] for row in rows)

    monaco = [row for row in rows if "jsdelivr" in row["url"]]
    checker = [row for row in rows if "ty_wasm" in row["url"]]
    shell = [row for row in rows if row not in monaco and row not in checker]

    measured = {
        "requests": len(rows),
        "wire": part(rows, "wire"),
        "decoded": part(rows, "decoded"),
        "gzipped": part(rows, "gzipped"),
        "bodies_not_readable": unread,
        "shell": {"requests": len(shell), "wire": part(shell, "wire"), "decoded": part(shell, "decoded")},
        "monaco": {"requests": len(monaco), "wire": part(monaco, "wire"), "decoded": part(monaco, "decoded")},
        "ty_wasm": {"requests": len(checker), "wire": part(checker, "wire"), "decoded": part(checker, "decoded")},
        "comparable": False,
        "why_not_comparable": (
            "a pip-installed wheel with bundled JavaScript, served by the application's own "
            "development server, which compresses only part of what it sends; the other four "
            "load unbundled ES modules from a CDN, which compresses all of it. This one also "
            "carries an IDE none of the others has: Monaco from a CDN and ty as WebAssembly, "
            "reported separately above so the editor and the type checker can be priced apart"
        ),
        "responses": sorted(rows, key=lambda row: -row["wire"]),
        "reported_by_others": REPORTED,
    }
    print(
        f"\npanel-reactflow page load: {measured['wire']:,} B wire, "
        f"{measured['decoded']:,} B decoded, {measured['gzipped']:,} B if compressed, "
        f"{len(rows)} requests"
        f"\n  shell {measured['shell']['wire']:,} B / {measured['shell']['requests']} req"
        f"  monaco {measured['monaco']['wire']:,} B / {measured['monaco']['requests']} req"
        f"  ty {measured['ty_wasm']['wire']:,} B / {measured['ty_wasm']['requests']} req"
        f"\n  decoded is short by whatever these weigh, whose bodies a stream does not keep: {unread}"
    )

    assert rows, "something was fetched"
    assert measured["shell"]["wire"] > 0, "the application's own server served the editor"
    assert measured["monaco"]["requests"] == 3, (
        "the whole editor, its python grammar and its icon font, and not the 604 kB chunk"
        f" a second copy of Monaco would cost: {[row['url'] for row in monaco]}"
    )
    assert any(row["url"] == components.CODICON for row in monaco), (
        f"the icon font is fetched from the CDN, not from this server: {[row['url'] for row in monaco]}"
    )
    assert measured["ty_wasm"]["wire"] > 10_000_000, "and the type checker is the WebAssembly it says it is"

    (shots / "bytes.json").write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_no_two_screenshots_are_the_same(shots):
    """Two identical files under different names is the easiest thing to ship
    here and the hardest to notice, so it is asserted rather than eyeballed.
    """
    files = {name: shots / f"{name}.png" for name in (*NAMED, *EXTRA)}
    missing = [name for name, path in files.items() if not path.exists()]
    if missing:
        pytest.skip(f"not taken in this run: {missing}")

    digests: dict[str, str] = {}
    for name, path in files.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest not in digests.values(), (
            f"{name} is byte-identical to {[k for k, v in digests.items() if v == digest]}"
        )
        digests[name] = digest
    assert len(digests) == len(NAMED) + len(EXTRA)


def test_the_type_checker_is_addressed_beside_the_page_and_not_at_the_root():
    """Or it is only found where the app is served from the root.

    The static build deploys under a path. Rooted at `/`, the loader asked the
    site's root for the checker, got a 404 from a server that had it one
    directory along, and the editor lost every diagnostic the moment it was
    deployed anywhere other than a bare host.
    """
    from awl.ui import panel_reactflow

    if not panel_reactflow.ty_assets():
        pytest.skip("no ty build to address")
    editor = panel_reactflow.open_sample()
    url = editor.source_pane.ty_url
    assert url and not url.startswith("/"), f"{url!r} is resolved against the host, not the page"
    assert url.endswith("ty_wasm.js")


def test_the_arrowhead_points_down_the_line_it_ends(page, live):
    """Three rounds were reported as a folded arrow, and three tests passed over it.

    Every assertion was about the line: the path joins the blocks, it is
    centred, the head is wide enough. None was about *direction*. A
    ``smoothstep`` path over two anchors sharing an x emits every waypoint
    twice, so its last segment has zero length; the marker is
    ``orient="auto-start-reverse"``, takes its angle from that segment's
    tangent, finds none, falls back to zero degrees and points right. Its
    polyline is ``-5,-4 0,0 -5,4``, so the head hung off the left of a vertical
    line.

    Measured in pixels, because a marker has no node where it is painted: it is
    a definition in ``defs`` and its rectangle is the definition's. Reading the
    DOM is what let every earlier test agree with a picture nobody could use.
    """
    import io
    import itertools
    import re

    from PIL import Image

    open_editor(page, live)

    paths = page.locator("path.react-flow__edge-path")
    assert paths.count(), "the level draws no connectors"
    for index in range(paths.count()):
        d = paths.nth(index).get_attribute("d")
        numbers = [float(n) for n in re.findall(r"-?[0-9.]+", d)]
        points = list(zip(numbers[::2], numbers[1::2], strict=True))
        assert len(points) >= 2, d
        repeated = [pair for pair in itertools.pairwise(points) if pair[0] == pair[1]]
        assert not repeated, f"a zero-length segment leaves the head no tangent: {d} repeats {repeated}"

    blocks = page.locator(".awl-block")
    boxes = sorted(
        (box for box in (blocks.nth(i).bounding_box() for i in range(blocks.count())) if box and box["height"] > 20),
        key=lambda box: box["y"],
    )
    first, second = boxes[0], boxes[1]
    clip = {
        "x": first["x"] + first["width"] / 2 - 15,
        "y": first["y"] + first["height"],
        "width": 30,
        "height": second["y"] - (first["y"] + first["height"]),
    }
    shot = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("L")
    width, height = shot.size
    # Taken from the image rather than assumed: the viewport's device scale is
    # the fixture's business, and a threshold in device pixels would pass or
    # fail on a setting that has nothing to do with the arrow.
    scale = width / clip["width"]
    # Rows the block's own border draws are dropped by shape rather than by
    # colour: an antialiased 1.8px stroke and a 1px border land in the same
    # range of greys, but a border runs the width of the clip and a connector
    # never does. Counting it made the arrow look as if it reached the block
    # whatever it did.
    rows = [[x for x in range(width) if shot.getpixel((x, y)) < 200] for y in range(height)]
    ink = [row if len(row) < 0.8 * width else [] for row in rows]
    drawn = [(y, row) for y, row in enumerate(ink) if row]
    assert drawn, "nothing is drawn between the two blocks"

    # The head is the widest run of ink, and it must be at the bottom of the
    # join and centred on the line. Pointing right puts it off centre; pointing
    # up puts it at the top.
    widest = max(drawn, key=lambda item: len(item[1]))
    first_row, last_row = drawn[0][0], drawn[-1][0]
    assert widest[0] > first_row, "the widest part of the connector is at its start, so the head points back"
    # In the lower half of what is drawn. Not *at* the last row: a head pointing
    # down is widest at its base and tapers to its point, so the base sits a few
    # rows above the tip.
    assert widest[0] >= first_row + (last_row - first_row) / 2, "the head is in the upper half, so it points up"
    centre = (width - 1) / 2
    middle = (widest[1][0] + widest[1][-1]) / 2
    assert abs(middle - centre) <= scale, f"the head sits at {middle:.1f}, the line at {centre:.1f}"
    # Against the line it ends rather than an absolute width, so this says
    # "wider than the line" at any zoom: a head the width of its own stroke is
    # the speck an unscaled marker degenerates to.
    shaft = min(len(row) for _y, row in drawn[: max(1, len(drawn) // 3)])
    assert len(widest[1]) >= 2 * shaft, f"the head is {len(widest[1])} across and the line is {shaft}"

    # And the point is visible. The marker puts its tip on the path's last
    # vertex, so an anchor on the block's own edge lands the tip under the block
    # and the arrow arrives looking blunt. The ink must stop clear of the
    # bottom of the join, and must taper: a clipped head ends at its widest.
    assert drawn[-1][0] <= height - 1 - scale, "the tip runs under the block it points at"
    assert len(drawn[-1][1]) < len(widest[1]), "the head ends at its widest, so its point is cut off"

    page.screenshot(path=str(SHOTS / "36-arrowhead.png"), clip=clip)
