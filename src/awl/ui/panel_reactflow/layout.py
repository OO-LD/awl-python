"""Placing the block tree on a React Flow canvas, the way a designer would.

React Flow lays nothing out. That is usually held against it, and here it is the
point: Sequential Workflow Designer's shape is a *choice*, and a canvas that
computes its own geometry can make the same choice. So this measures the tree
bottom-up and places it top-down, and produces three things React Flow already
knows how to draw:

- **containers**, as parent nodes with ``parentId`` and ``extent: "parent"`` on
  what they hold, so a loop's body is inside a bounded region rather than beside
  it;
- **lanes**, as containers of their own, side by side, so an ``if`` is a
  ``then`` column and an ``else`` column that rejoin below rather than two
  labelled edges leaving one node;
- **drop zones**, as real nodes between every pair of statements, so a drag from
  the toolbox has somewhere honest to land and the thing it lands on already
  knows the document path it writes into.

The edges are the plan's, mapped onto those nodes. Which of them the layout
already expresses is decided here and nowhere else, and there are three ways it
can express one: a lane's label, the container's own outline, and a connector
between two blocks standing in one lane. What is left over is drawn as an arc
through a gutter kept clear beside the container it has to escape. Nothing keys
on a shape or a class name, so a container the plan reports no edge out of gets
no arc, and one it does gets exactly as many as the plan reports.

Every block fills the lane it sits in rather than being centred at a fixed
width. That is geometry in service of the edges: ``panel-reactflow`` renders
every input handle as ``Position.Left`` and every output as ``Position.Right``,
and React Flow shapes a step path from those, so the vertical leg of an edge
always lands half way between the two anchors and nothing here can move it. Two
blocks in one lane therefore share a centre line and the connector between them
is one straight drop with the arrowhead pointing down it; two blocks at
different indents do not, and the connector ends in a sideways stub that hooks
into the top of the block it arrives at. That is why an edge leaving a container
is drawn *from the container*: the block it really leaves is inside a lane and
sits at a different indent from the block it reaches, and the container does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from awl.ui.panel_reactflow import tree

__all__ = ["GEOMETRY", "Wiring", "edges_for", "place", "route"]

#: Every size the canvas is built from, in one place so tuning is one edit.
GEOMETRY = {
    # The narrowest a lane may be. Wider than this, every block in the lane
    # takes the lane's width, so a column of them shares two vertical edges.
    "block_width": 320,
    # One line: the kind, the source it covers, and its two buttons.
    "block_height": 36,
    # The comment line under the header, on every block that can carry one.
    "note_height": 22,
    # A second line, only on blocks that have typed values to show. Four
    # pixels taller than the tallest widget it holds, so a spinner is
    # centred in the strip rather than flush against the node's border.
    "fields_height": 52,
    # The strip a drop lands on, before and after every block.
    "zone_height": 13,
    # Between a zone and the block it sits against. Large enough that the
    # connector between two blocks is a line and not a three pixel nub: at five
    # the arrowhead alone covered the whole gap.
    "gap": 11,
    # A lane's own label, and the padding around what it holds.
    "lane_head": 18,
    "lane_pad_x": 10,
    "lane_pad_bottom": 8,
    # A container's header is the block itself: its condition is edited there.
    "container_head": 42,
    "container_pad_x": 10,
    "container_pad_bottom": 8,
    # Kept clear on the right of a container an arc has to escape, so the arc
    # has somewhere to run that is not over the statements it is passing. Only
    # where there is one: a loop reserved this for a `repeat` that the region
    # around its body already expresses.
    "gutter": 46,
    # Between the lanes of a branch.
    "lane_gap": 14,
    # How hard a step path turns its corners.
    "corner": 9,
    # How far above a block its incoming edge stops. The arrowhead's marker puts
    # its point on the path's last vertex, so an anchor on the block's own edge
    # lands the tip under the block and the arrow arrives looking blunt.
    "head_clearance": 5,
}


def lane_id(lane: tree.Lane) -> str:
    """Return the canvas id of a lane."""
    return "lane:" + tree.path_id(lane.path)


def zone_id(lane: tree.Lane, index: int) -> str:
    """Return the canvas id of the drop zone before position *index*."""
    return f"zone:{tree.path_id(lane.path)}:{index}"


def block_height(block: tree.Block) -> float:
    """Return how tall a block's node is, which is what its view must fit."""
    height = GEOMETRY["block_height"]
    if block.notable:
        height += GEOMETRY["note_height"]
    if block.fields:
        height += GEOMETRY["fields_height"]
    return height


def head_height(block: tree.Block) -> float:
    """Return how far down a container's lanes start.

    Under the container's own view, whatever that view turned out to be. Fixed
    at the height of a bare header line, a container carrying a comment had its
    lanes drawn 22 pixels too high and the ``THEN`` label sat on top of the
    ``# note`` field of the ``if`` it belongs to.
    """
    return GEOMETRY["container_head"] + (GEOMETRY["note_height"] if block.notable else 0)


# -- measuring -----------------------------------------------------------------


def _measure_block(block: tree.Block, gutters: set[str]) -> tuple[float, float]:
    """Return the narrowest a block may be, containers measured from what they hold."""
    if not block.lanes:
        return GEOMETRY["block_width"], block_height(block)

    sizes = [_measure_lane(lane, gutters) for lane in block.lanes]
    width = sum(size[0] for size in sizes) + GEOMETRY["lane_gap"] * (len(sizes) - 1)
    height = max(size[1] for size in sizes)
    return (
        width + 2 * GEOMETRY["container_pad_x"] + _gutter(block, gutters),
        height + head_height(block) + GEOMETRY["container_pad_bottom"],
    )


def _gutter(block: tree.Block, gutters: set[str]) -> float:
    """Return the strip kept clear on a block's right for an edge to run up.

    Only where an arc has to get out of this container, which is a fact about
    the plan's edges and is decided before anything is placed. Keyed on the
    role, a loop reserved 46 pixels of empty canvas for an arc that the
    containment already expresses and that is no longer drawn.
    """
    return GEOMETRY["gutter"] if block.id in gutters else 0.0


def _measure_lane(lane: tree.Lane, gutters: set[str]) -> tuple[float, float]:
    """Return the size of a lane's own box, label and padding included."""
    width, height = _measure_contents(lane, gutters)
    return width + 2 * GEOMETRY["lane_pad_x"], height + GEOMETRY["lane_head"] + GEOMETRY["lane_pad_bottom"]


def _measure_contents(lane: tree.Lane, gutters: set[str]) -> tuple[float, float]:
    """Return the size of the stack of zones and blocks inside a lane."""
    sizes = [_measure_block(block, gutters) for block in lane.blocks]
    width = max([GEOMETRY["block_width"], *[size[0] for size in sizes]])
    height = sum(size[1] for size in sizes)
    height += (len(sizes) + 1) * GEOMETRY["zone_height"]
    height += 2 * len(sizes) * GEOMETRY["gap"]
    return width, height


# -- placing -------------------------------------------------------------------


class _Placer:
    """Walks the tree once, emitting nodes with parents before children."""

    def __init__(self, view: Any, gutters: set[str]) -> None:
        self.view = view
        self.gutters = gutters
        self.nodes: list[dict[str, Any]] = []
        self.boxes: dict[str, tuple[float, float, float, float]] = {}
        self.lane_kinds: dict[str, str] = {}

    def emit(
        self,
        node_id: str,
        kind: str,
        box: tuple[float, float, float, float],
        parent: str | None,
        origin: tuple[float, float],
        **extra: Any,
    ) -> None:
        """Record one node, in canvas coordinates and in its parent's."""
        x, y, width, height = box
        node: dict[str, Any] = {
            "id": node_id,
            "type": kind,
            "position": {"x": x - origin[0], "y": y - origin[1]},
            "label": "",
            "data": {},
            "draggable": False,
            "connectable": False,
            "selectable": kind not in ("zone", "lane"),
            "deletable": False,
            **extra,
        }
        node["style"] = {"width": width, "height": height, **node.get("style", {})}
        if parent:
            node["parentId"] = parent
            node["extent"] = "parent"
        self.nodes.append(node)
        self.boxes[node_id] = box

    def lane(
        self,
        lane: tree.Lane,
        x: float,
        y: float,
        width: float,
        parent: str | None,
        origin: tuple[float, float],
        boxed: bool,
    ) -> None:
        """Place a statement list, optionally inside a box of its own.

        The level's own list is not boxed: it *is* the canvas. Every list a
        container owns is, because the box is what makes "inside the loop"
        something a reader can see rather than infer from two edge labels.
        """
        if boxed:
            _, height = _measure_lane(lane, self.gutters)
            self.emit(
                lane_id(lane),
                "lane",
                (x, y, width, height),
                parent,
                origin,
                view=self.view.lane(lane),
            )
            self.lane_kinds[lane_id(lane)] = lane.label
            parent, origin = lane_id(lane), (x, y)
            x += GEOMETRY["lane_pad_x"]
            y += GEOMETRY["lane_head"]
            width -= 2 * GEOMETRY["lane_pad_x"]

        cursor = y
        for index, block in enumerate(lane.blocks):
            self.emit(
                zone_id(lane, index),
                "zone",
                (x, cursor, width, GEOMETRY["zone_height"]),
                parent,
                origin,
                view=self.view.zone(lane, index),
            )
            cursor += GEOMETRY["zone_height"] + GEOMETRY["gap"]
            cursor = self.block(block, x, cursor, width, parent, origin) + GEOMETRY["gap"]
        self.emit(
            zone_id(lane, len(lane.blocks)),
            "zone",
            (x, cursor, width, GEOMETRY["zone_height"]),
            parent,
            origin,
            view=self.view.zone(lane, len(lane.blocks)),
        )

    def block(
        self,
        block: tree.Block,
        x: float,
        y: float,
        width: float,
        parent: str | None,
        origin: tuple[float, float],
    ) -> float:
        """Place one block across the width it was given. Returns its bottom.

        Across and not centred. Two blocks in one lane then share both vertical
        edges, which is what lets the back edge's vertical leg be computed
        rather than guessed: React Flow puts it half way between the two
        anchors and offers no way to move it.
        """
        _, own_height = _measure_block(block, self.gutters)
        self.emit(
            block.id,
            block.role,
            (x, y, width, own_height),
            parent,
            origin,
            view=self.view.block(block),
        )
        if not block.lanes:
            return y + own_height

        inner_x = x + GEOMETRY["container_pad_x"]
        inner_y = y + head_height(block)
        # The slack a stretched container gained is shared out among its lanes
        # rather than left on the right, where it would read as an empty third
        # lane. The gutter is taken off first, because it is not slack: it is
        # the strip the back edge runs in.
        room = width - 2 * GEOMETRY["container_pad_x"] - _gutter(block, self.gutters)
        widths = [_measure_lane(lane, self.gutters)[0] for lane in block.lanes]
        slack = (room - sum(widths) - GEOMETRY["lane_gap"] * (len(widths) - 1)) / len(widths)
        for lane, lane_width in zip(block.lanes, widths, strict=True):
            self.lane(lane, inner_x, inner_y, lane_width + slack, block.id, (x, y), boxed=True)
            inner_x += lane_width + slack + GEOMETRY["lane_gap"]
        return y + own_height


def place(
    root: tree.Lane, view: Any, gutters: set[str] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Return the React Flow nodes for a level, and where each of them went.

    Parameters
    ----------
    root : tree.Lane
        The level to place.
    view : Any
        Builds the Panel object inside each node.
    gutters : set of str, optional
        The containers an arc has to get out of, from :func:`edges_for`. Only
        those keep a strip clear on the right.
    """
    placer = _Placer(view, gutters or set())
    width, _ = _measure_contents(root, placer.gutters)
    placer.lane(root, 0, 0, width, None, (0, 0), boxed=False)
    return placer.nodes, placer.boxes, placer.lane_kinds


# -- the plan's edges ----------------------------------------------------------


@dataclass
class Wiring:
    """What became of every edge the plan reports at one level.

    Attributes
    ----------
    edges : list of dict
        The React Flow edges, which is what is drawn.
    entered : dict
        Lane id to the plan kind that enters it, which is what the lane says.
    enclosed : dict
        Block id to the kind of the edge out of it that the containment
        expresses. A loop's ``repeat`` lands here: the container already holds
        what repeats, so the arc added nothing and crossed everything.
    escaping : set of str
        The containers an arc still has to get out of, so the placement can
        keep a strip clear beside exactly those.
    """

    edges: list[dict[str, Any]] = field(default_factory=list)
    entered: dict[str, str] = field(default_factory=dict)
    enclosed: dict[str, str] = field(default_factory=dict)
    escaping: set[str] = field(default_factory=set)


class _Structure:
    """Which lane each block stands in, and which block owns each lane."""

    def __init__(self, root: tree.Lane) -> None:
        self.by_plan: dict[str, tree.Block] = {}
        self.lane_of: dict[str, str] = {}
        self.blocks_in: dict[str, list[str]] = {}
        self.owner_of: dict[str, str | None] = {}
        self.lanes_of: dict[str, list[tree.Lane]] = {}
        self._visit(root, None)

    def _visit(self, lane: tree.Lane, owner: str | None) -> None:
        name = lane_id(lane)
        self.owner_of[name] = owner
        self.blocks_in[name] = [block.id for block in lane.blocks]
        for block in lane.blocks:
            self.lane_of[block.id] = name
            if block.plan:
                self.by_plan[block.plan] = block
            self.lanes_of[block.id] = block.lanes
            for inner in block.lanes:
                self._visit(inner, block.id)

    def holders(self, node_id: str) -> list[str]:
        """Return the containers *node_id* sits inside, innermost first."""
        found: list[str] = []
        at: str | None = node_id
        while at is not None:
            at = self.owner_of[self.lane_of[at]]
            if at is not None:
                found.append(at)
        return found

    def encloses(self, outer: str, inner: str) -> bool:
        """Return whether *outer* is a container *inner* sits inside."""
        return outer in self.holders(inner)

    def leaving(self, node_id: str, target_id: str) -> str | None:
        """Return the block a connector to *target_id* is drawn from, or None.

        The source itself when the two stand in one lane. Otherwise the
        container the source has to leave to reach the target, which is the
        block that really sits above it on the canvas: a block inside a lane is
        at a different indent from whatever follows the container, and an edge
        between two anchors that do not share a centre line ends in a sideways
        stub hooked into the top of the block it arrives at.
        """
        at: str | None = node_id
        while at is not None:
            lane = self.lane_of[at]
            siblings = self.blocks_in[lane]
            index = siblings.index(at)
            if index + 1 < len(siblings):
                return at if siblings[index + 1] == target_id else None
            at = self.owner_of[lane]
        return None


def edges_for(root: tree.Lane, plan_edges: list[dict[str, Any]]) -> Wiring:
    """Return what the canvas does with each of the plan's edges at one level.

    Parameters
    ----------
    root : tree.Lane
        The level, already built.
    plan_edges : list of dict
        ``flow(scope)["edges"]``, between plan step identities.

    Returns
    -------
    Wiring
        What is drawn, what a lane says instead, and what the containment says
        instead.

    Notes
    -----
    Four outcomes, and which one an edge gets is decided from the plan and the
    tree, never from what a container looks like.

    **A lane's label.** An edge into the first block of one of the source's own
    lanes is what that lane already says, and the label carries the plan's own
    word, which is why a ``for`` says ``each_item`` where a ``while`` says
    ``when_true``. An edge that leaves the container while one of its lanes
    stands empty is that empty lane: an ``if`` with no ``else`` sends control
    past itself on ``when_false``, and with an ``else`` column drawn on screen a
    ``when_false`` arrow pointing at the statement *after* the ``if`` names the
    wrong place. The connector is still drawn, because control really does carry
    on; it carries no label, because the lane has it.

    **The container's own outline.** An edge back into a container that already
    encloses the source is a loop's ``repeat``, and the region drawn around the
    body is what says the body repeats. The arc said it a second time, in a
    gutter kept clear across the whole height of the loop.

    **A connector.** Between two blocks standing in one lane, drawn top to
    bottom. An edge out of a container is drawn *from the container*, because
    that is the block the target stands under; two of them onto one target are
    one connector, which is why the last statement of a ``then`` no longer
    draws its own arrow to the statement the ``if`` already points at.

    **An arc**, for anything left, through a gutter kept clear beside the
    container it has to escape.
    """
    structure = _Structure(root)
    wiring = Wiring()
    connectors: dict[tuple[str, str], list[str]] = {}
    open_lanes: dict[str, list[tree.Lane]] = {
        block: [lane for lane in lanes if not lane.blocks] for block, lanes in structure.lanes_of.items()
    }

    for edge in plan_edges:
        source = structure.by_plan.get(edge.get("from", ""))
        target = structure.by_plan.get(edge.get("to", ""))
        if source is None or target is None:
            continue
        kind = edge.get("kind", "next")

        heads = {lane.blocks[0].id: lane for lane in structure.lanes_of.get(source.id, []) if lane.blocks}
        if target.id in heads:
            wiring.entered[lane_id(heads[target.id])] = kind
            continue

        if structure.encloses(target.id, source.id):
            wiring.enclosed[source.id] = kind
            continue

        from_block = structure.leaving(source.id, target.id)
        if from_block is None:
            # Every container between the two, not only the innermost: a
            # ``break`` two lanes deep has to get out of the branch it is in and
            # out of the loop it breaks, and a strip kept clear beside one of
            # them leaves the arc crossing the other.
            wiring.escaping.update(
                holder for holder in structure.holders(source.id) if not structure.encloses(holder, target.id)
            )
            wiring.edges.append(_back_edge(source.id, target.id, kind))
            continue

        spare = open_lanes.get(source.id) or []
        if spare and source.id == from_block:
            wiring.entered[lane_id(spare.pop(0))] = kind
            kind = "next"
        connectors.setdefault((from_block, target.id), []).append(kind)

    for (from_block, target_id), kinds in connectors.items():
        # Labelled only when it stands for one edge with one reason. Two
        # statements leaving a branch by the same door are one connector, and
        # writing one of their two reasons on it would name the other's path.
        alone = len(kinds) == 1 and kinds[0] != "next"
        wiring.edges.append(_flow_edge(from_block, target_id, kinds[0] if alone else "next"))
    return wiring


def _flow_edge(source: str, target: str, kind: str) -> dict[str, Any]:
    """One block to the next: down, across if it has to, down again.

    ``offset: 0`` is the whole shape. The library declares every input handle
    ``Position.Left`` and every output ``Position.Right``, so React Flow leaves
    a block sideways and arrives at the next one sideways, and the default
    twenty pixel stub turned every connector between two stacked blocks into a
    flat Z three pixels tall. With no stub the same path collapses to the two
    corners it actually needs, which for two blocks sharing a centre line is one
    straight vertical drop.
    """
    return {
        "id": f"{source}->{target}",
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": "in",
        "type": "smoothstep",
        "pathOptions": {"offset": 0, "borderRadius": GEOMETRY["corner"]},
        "label": "" if kind == "next" else kind,
        "data": {"kind": kind, "drawn": "flow"},
        "style": {"stroke": "#64748b", "strokeWidth": 1.8},
        # Sized against the gap it lands in rather than left at the library's
        # default. A marker scales with the viewport and the stroke does not, so
        # an arrowhead that reads at full zoom is three pixels of speck with a
        # level fitted into the page, which is where a reader starts.
        "markerEnd": {"type": "arrowclosed", "width": 20, "height": 20, "color": "#64748b"},
    }


def _back_edge(source: str, target: str, kind: str) -> dict[str, Any]:
    """The edge a tree cannot hold: out to the right, up the gutter, back in."""
    return {
        "id": f"{source}->{target}",
        "source": source,
        "target": target,
        "sourceHandle": "tail",
        "targetHandle": "back",
        "type": "smoothstep",
        "pathOptions": {"offset": 0, "borderRadius": GEOMETRY["corner"]},
        "label": kind,
        "animated": True,
        "data": {"kind": kind, "drawn": "back"},
        "style": {"stroke": "#7c3aed", "strokeWidth": 1.8, "strokeDasharray": "7 4"},
        "markerEnd": {"type": "arrowclosed", "width": 17, "height": 17, "color": "#7c3aed"},
    }


def route(
    edges: list[dict[str, Any]], boxes: dict[str, tuple[float, float, float, float]]
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Say where each back edge's vertical leg will land, and check it is clear.

    React Flow runs that leg half way between the two anchors and takes no
    argument about it, so this cannot move the line: it computes where the line
    will be. Both anchors are right edges, the source's is its lane's and the
    target's is its container's, and the gutter is exactly the strip between
    them, so the midpoint is inside the gutter whenever the placement above put
    it there.

    Returns
    -------
    tuple
        The edges, and the x each back edge's vertical leg runs at, by edge id,
        which is what a test asserts against the blocks the arc passes.
    """
    legs: dict[str, float] = {}
    for edge in edges:
        source = boxes.get(edge["source"])
        target = boxes.get(edge["target"])
        if edge.get("data", {}).get("drawn") != "back":
            if source and target and _aligned(source, target):
                _make_straight(edge)
            continue
        if not source or not target:
            continue
        legs[edge["id"]] = ((source[0] + source[2]) + (target[0] + target[2])) / 2
    return edges, legs


def _aligned(source: tuple[float, float, float, float], target: tuple[float, float, float, float]) -> bool:
    """Whether two boxes share a centre line, so the join between them is straight."""
    return abs((source[0] + source[2] / 2) - (target[0] + target[2] / 2)) < 0.5


def _make_straight(edge: dict[str, Any]) -> None:
    """Draw a join between two blocks on one centre line as a straight line.

    A step path over two anchors that share an x emits every waypoint twice, so
    the last segment of the path has zero length. The arrowhead is
    ``orient="auto-start-reverse"``, which takes its angle from that segment's
    tangent, and a segment of no length has no tangent: the marker falls back to
    zero degrees and points *right*. Its polyline is ``-5,-4 0,0 -5,4``, so a
    right-pointing head hangs off the left of a vertical line, which is what
    three rounds of this were reported as a folded or crumbled arrow.

    Straight is also what it is. There are no corners between two blocks on one
    centre line, so there is nothing for a step path to compute.
    """
    edge["type"] = "straight"
    edge.pop("pathOptions", None)
