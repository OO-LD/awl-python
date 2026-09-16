"""One level of a module as a tree of blocks, lanes and containers.

:meth:`~awl.ui.EditorModel.flow` is flat: every step at a scope arrives in one
list, and what encloses what is carried only by the *kind* of the edges between
them. A canvas drawn from that alone puts eleven steps at one indent, which is
what the two React Flow variants did and what they were faulted for.

The nesting is already in the compact document, because the compact document is
the syntax tree. So this reads the document and produces the shape a canvas can
lay out: a :class:`Lane` is a statement list, a :class:`Block` is a statement,
and a block that owns statement lists carries them as lanes of its own. A loop
has one lane; an ``if`` has two, and they are drawn side by side.

The plan is still what says how control moves, and it is read for three things
the document cannot say: which call opens into another level, which span the
trace attributes an event to, and which edges exist between the blocks,
including the ``repeat`` that a tree has no way to hold.

Every block's ``path`` is its path in the document, and that is the whole reason
a gesture on the canvas is writable: a drop reports a lane and an index, and the
lane's path is already the argument :func:`awl.editor.add_step` wants.

Comments are the one thing here that the document cannot supply. ``ast`` has no
comment node, so the compact document has none either, and a block's own note
has to be read off the source it covers. That reading is
:meth:`~awl.ui.EditorModel.trivia`'s and not this module's: every canvas wants
it, this one tokenized the source itself, and the two copies drifted, so a note
written on a statement whose first line ends inside a string went *into the
string*. What comes back is a *range*, not a rewrite, so a comment edit is a
span patch like a literal's and survives being made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DECLARATIONS",
    "OPTIONAL_SLOTS",
    "Block",
    "Lane",
    "build",
    "declarations",
    "find_scope",
    "movable",
    "names_of",
    "path_id",
    "path_of",
    "span_key",
    "walk",
]

#: Statements a move may neither carry nor cross. A statement list is not a
#: flow: an import below the class that decorates with it still draws exactly
#: the same, and the module raises ``NameError`` the next time it is run.
DECLARATIONS = {"ClassDef", "FunctionDef", "AsyncFunctionDef", "Import", "ImportFrom", "Global", "Nonlocal"}

#: Statements that own one nested statement list. The value is the label the
#: plan's edge into that list would otherwise have to supply on its own.
LOOPS = {"While": "loop", "For": "loop", "AsyncFor": "loop"}

#: Statements that own named lists, drawn as lanes side by side. The order is
#: the order the lanes appear on the canvas, left to right.
BRANCH_LANES = (("then", "body"), ("else", "orelse"))

#: The lane a loop's body is written into.
BODY_SLOT = "body"

#: Statement lists that are allowed to hold nothing. A suite has to carry a
#: statement, so emptying a body puts a ``pass`` in it; an ``if`` with an empty
#: ``else`` is an ``if``, and writing ``else: pass`` for one would put a
#: statement in the file that the reader never asked for.
OPTIONAL_SLOTS = {"orelse", "finalbody"}

#: Keys holding *other statements* rather than values of this one. A loop's
#: form must not offer to edit the literals of the statements it encloses:
#: those are blocks of their own, with forms of their own.
_CHILD_KEYS = {"body", "orelse", "finalbody", "handlers", "test"}


@dataclass
class Lane:
    """One statement list, and the blocks in it.

    Attributes
    ----------
    path : list
        The document path of the list itself, which is what a drop writes into.
    label : str
        What the canvas writes above the lane. ``then`` and ``else`` for a
        branch; for a loop it is the kind of the plan's edge into the body,
        so a ``for`` says ``each_item`` where a ``while`` says ``when_true``.
    blocks : list of Block
        In source order.
    """

    path: list[Any]
    label: str = ""
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Block:
    """One statement, and the lanes it owns.

    Attributes
    ----------
    path : list
        Its path in the document, which is its identity everywhere else.
    kind : str
        The Python node type: ``Assign``, ``While``, ``If``, ``FunctionDef``.
    role : str
        What the canvas draws it as: ``step``, ``loop``, ``branch``, ``level``,
        ``class``, ``import``, ``return`` or ``opens``.
    text : str
        The source the statement covers, verbatim.
    label : str
        Its first line, which is what the block says on the canvas.
    span : list or None
        ``[start_line, start_col, end_line, end_col]``, the join key for the
        trace overlay and the range an edit is written back into.
    plan : str
        The identity of the plan step this was drawn from, or ``""``.
    fields : list of dict
        ``label``, ``path`` and ``value`` for every value a form may set.
    condition, condition_span
        The test of a loop or a branch, edited as the text it is.
    opens : str
        The scope a double-click descends into, or ``""``.
    calls : str
        The name this statement calls, or ``""`` when it calls nothing. Kept
        beside ``resolved`` because the two together are what tell a call that
        resolved to nothing from a statement that never called anything: an
        unread function and an empty one are different claims, and ``resolved``
        alone is ``""`` for both.
    resolved : str
        What its callee resolved to, qualified with the module when that is not
        this one, or ``""`` when nothing resolved.
    note : str
        The comment this statement carries, without its ``#``, or ``""``.
    note_span : list or None
        The range a note edit rewrites. Zero width when there is no comment
        yet, which is where one would be written.
    note_where : str
        ``beside`` for a comment on the statement's own line, ``above`` for one
        on the line before it, ``""`` when there is none.
    lanes : list of Lane
        The statement lists this block owns.
    """

    path: list[Any]
    kind: str
    role: str
    text: str = ""
    label: str = ""
    span: list[int] | None = None
    plan: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)
    condition: str = ""
    condition_span: list[int] | None = None
    opens: str = ""
    opens_module: str = ""
    calls: str = ""
    resolved: str = ""
    note: str = ""
    note_span: list[int] | None = None
    note_where: str = ""
    contains: int = 0
    lanes: list[Lane] = field(default_factory=list)

    @property
    def id(self) -> str:
        """The dotted path, which is what a node on the canvas is called."""
        return path_id(self.path)

    @property
    def notable(self) -> bool:
        """Whether the canvas offers this block a comment line.

        Every block that covers source does, whether or not it carries a
        comment today: a note line that appears only where one already exists
        is a viewer, and the requirement is that a comment round trips.
        """
        return self.note_span is not None


def path_id(path: list[Any]) -> str:
    """Return the dotted string a canvas carries as a node id."""
    return ".".join(str(part) for part in path)


def path_of(node_id: str) -> list[Any]:
    """Return the document path a node id names.

    The inverse of :func:`path_id`. Digits are indices and everything else is a
    key, which is enough because a compact document has no numeric keys.
    """
    return [int(part) if part.lstrip("-").isdigit() else part for part in node_id.split(".") if part != ""]


def span_key(span: Any) -> tuple[int, int, int, int] | None:
    """Return a span as a comparable tuple, from either shape it arrives in.

    The document writes a span as a list and the plan writes it as a dict with
    a file in it. They are the same four numbers and they are the join key
    between the canvas, the trace and the source, so both reduce to one thing.
    """
    if isinstance(span, list | tuple) and len(span) == 4:
        return (span[0], span[1], span[2], span[3])
    if isinstance(span, dict) and "start_line" in span:
        return (span["start_line"], span["start_col"], span["end_line"], span["end_col"])
    return None


def find_scope(document: dict[str, Any], scope: str) -> list[Any]:
    """Return the path to the statement list a scope's steps live in.

    ``""`` is the module itself. Anything else is a function, found by name
    wherever it is declared, so a level nested three functions deep is located
    by the same rule as one at the top.
    """
    if not scope:
        return ["body"]

    found: list[list[Any]] = []

    def visit(node: Any, path: list[Any]) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, [*path, index])
            return
        if not isinstance(node, dict):
            return
        if node.get("@type") in ("FunctionDef", "AsyncFunctionDef") and node.get("name") == scope:
            found.append([*path, "body"])
        for key, value in node.items():
            if key in ("body", "orelse", "finalbody", "handlers"):
                visit(value, [*path, key])

    visit(document.get("body", []), ["body"])
    if not found:
        raise LookupError(f"no function called {scope!r} in this module")
    return found[0]


def walk(lane: Lane):
    """Yield every block under a lane, containers included, outermost first."""
    for block in lane.blocks:
        yield block
        for inner in block.lanes:
            yield from walk(inner)


def lanes_of(lane: Lane):
    """Yield every lane under *lane*, itself first."""
    yield lane
    for block in lane.blocks:
        for inner in block.lanes:
            yield from lanes_of(inner)


def _first_line(text: str) -> str:
    """Return the first line of *text*, marked when there was more."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return "..."
    head = lines[0].strip()
    if len(lines) > 1 and not head.endswith(":"):
        head = head + " ..."
    return head


def _label(node: dict[str, Any], text: str) -> str:
    """Return what the block says on the canvas.

    The source it covers, not a vocabulary term. Both React Flow variants wrote
    ``CALL / i = 0``, because the neutral vocabulary maps an assignment to a
    call: correct in the graph and strange on a canvas. A block that reads
    ``i = 0`` needs no legend.
    """
    if "literal" in node and isinstance(node.get("literal"), str):
        return '"""' + _first_line(node["literal"])[:44] + '"""'
    return _first_line(text)


def _kind(node: dict[str, Any]) -> str:
    """Return the statement's Python node type, or ``Expr`` for a bare value."""
    kind = node.get("@type")
    if isinstance(kind, list):
        return kind[0]
    return kind or "Expr"


def declarations(document: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return each class's declared field types, by class name then field name.

    The class already says what its fields are, so a form has no reason to
    guess from the value it happens to hold: ``target_voltage=4`` is a ``float``
    field carrying an integer literal, and a form that reads the value renders
    a spinner that steps in ones and cannot express ``4.35``.

    Read out of the document rather than out of the class object, because the
    document is what the editor has: nothing here imports the file being edited.
    """
    found: dict[str, dict[str, str]] = {}
    for node in document.get("body", []):
        if not isinstance(node, dict) or node.get("@type") != "ClassDef":
            continue
        fields: dict[str, str] = {}
        for statement in node.get("body", []):
            if not isinstance(statement, dict) or statement.get("@type") != "AnnAssign":
                continue
            target, annotation = statement.get("target"), statement.get("annotation")
            if isinstance(target, dict) and isinstance(annotation, dict) and "var" in annotation:
                fields[str(target.get("var"))] = str(annotation["var"])
        found[str(node.get("name"))] = fields
    return found


def _resolved(model: Any, identity: dict[str, Any] | None) -> str:
    """Return what a call resolved to, as much of it as is worth saying.

    Qualified with the module when that is not the one being edited, because a
    name resolved into a module that was never indexed is still *resolved*, and
    writing only ``drive`` would leave a reader no way to tell it from a
    function declared two lines up.
    """
    if not identity or not identity.get("symbol"):
        return ""
    where = identity.get("module") or ""
    if where and where != getattr(model, "module", ""):
        return f"{where}.{identity['symbol']}"
    return str(identity["symbol"])


def names_of(node: dict[str, Any]) -> str:
    """Return what a declaration is called, for a message about refusing it.

    An import declares the names it brings in rather than one of its own, and
    those are the names a refusal has to say: the move this exists to stop
    produced ``NameError: name 'dataclass' is not defined``, and a notice
    reading ``ImportFrom`` does not connect the two.
    """
    if node.get("name"):
        return str(node["name"])
    brought = node.get("names")
    if isinstance(brought, list) and brought:
        return ", ".join(str(entry) for entry in brought)
    return str(node.get("@type") or "this statement")


def movable(steps: list[Any], frm: int, to: int) -> str:
    """Return why a move is refused, or ``""`` if it is allowed.

    A statement list holds docstrings and declarations that are not steps, so
    position in the list is not position in the flow. Dragging an import below
    the class that decorates with it changes nothing a reader can see on the
    canvas and leaves a module that raises ``NameError`` on the next run, which
    is the worst shape a defect can take: silent, and blamed on the file.
    """
    if not 0 <= frm < len(steps) or not 0 <= to < len(steps):
        return "that position is not in this list"
    crossed = range(frm + 1, to + 1) if to > frm else range(to, frm)
    for index in (frm, *crossed):
        node = steps[index]
        if not isinstance(node, dict):
            continue
        kind = node.get("@type")
        if kind is None:
            return "a docstring stops being one if anything is moved above it"
        if kind in DECLARATIONS:
            return f"{names_of(node)} is a declaration, and a position beside it is not a position in the flow"
    return ""


def _fields(node: Any, path: list[Any], out: list[dict[str, Any]], root: bool = True) -> None:
    """Collect the values under *node* that :meth:`EditorModel.set_value` can set.

    Two kinds, and the form should not have to tell them apart: a literal node,
    which carries its own span, and a field of a **collapsed** constructor,
    which does not and is written back by rebuilding the call.
    """
    if isinstance(node, list):
        for index, item in enumerate(node):
            _fields(item, [*path, index], out, root=False)
        return
    if not isinstance(node, dict):
        return

    if isinstance(node.get("@type"), list):
        name = node["@type"][0]
        for key, value in node.items():
            if key in ("@type", "span") or isinstance(value, dict | list):
                continue
            out.append({
                "label": f"{name}.{key}",
                "name": key,
                "owner": name,
                "path": [*path, key],
                "value": value,
            })
        return

    if "literal" in node and "span" in node and not isinstance(node["literal"], str | type(None)):
        out.append({
            "label": ".".join(str(part) for part in path[-2:]) or "value",
            "name": str(path[-1]),
            "owner": "",
            "path": list(path),
            "value": node["literal"],
        })
        return

    for key, value in node.items():
        if key == "span" or (root and key in _CHILD_KEYS):
            continue
        _fields(value, [*path, key], out, root=False)


def _role(kind: str, block: Block) -> str:
    """Return what the canvas draws a leaf block as.

    A call that opens into another level is drawn differently from one that
    does not, because that difference is the whole navigation: a canvas that
    draws both the same says a level with a body and a name that was never
    resolved are the same thing.
    """
    if kind == "ClassDef":
        return "class"
    if kind in ("Import", "ImportFrom"):
        return "import"
    if kind == "Return":
        return "return"
    if block.opens:
        return "opens"
    return "step"


def build(model: Any, scope: str) -> Lane:
    """Return the block tree for one level of *model*.

    Parameters
    ----------
    model : awl.ui.EditorModel
        The document being edited.
    scope : str
        The function whose body to draw, or ``""`` for the module.

    Returns
    -------
    Lane
        The level's statement list, with every container carrying its own.
    """
    root = find_scope(model.document, scope)
    plan = model.flow(scope)
    by_span: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for step in plan["steps"]:
        key = span_key(step.get("span"))
        if key:
            by_span[key] = step
    levels = {entry["name"]: entry for entry in model.sublevels(scope)}
    kinds = _lane_kinds(plan["edges"], by_span)
    return _lane(model, _at(model.document, root), root, "", by_span, levels, kinds)


def _lane_kinds(edges: list[dict[str, Any]], by_span: dict[Any, dict[str, Any]]) -> dict[str, str]:
    """Return, per plan step, the kind of the edge that enters its body.

    A ``while`` enters its body on ``when_true`` and a ``for`` on ``each_item``.
    The lane says which, because the plan says which: a canvas that wrote
    ``then`` over a ``for``'s body would be inventing a word the plan never
    used, and nothing on screen would say so.
    """
    inner = {"when_true", "each_item"}
    found: dict[str, str] = {}
    for edge in edges:
        if edge.get("kind") in inner:
            found.setdefault(edge.get("from", ""), edge["kind"])
    return found


def _lane(
    model: Any,
    steps: list[Any],
    path: list[Any],
    label: str,
    by_span: dict[Any, dict[str, Any]],
    levels: dict[str, dict[str, Any]],
    kinds: dict[str, str],
) -> Lane:
    """Return one statement list as a lane."""
    return Lane(
        path=list(path),
        label=label,
        blocks=[_block(model, node, [*path, index], by_span, levels, kinds) for index, node in enumerate(steps)],
    )


def _block(
    model: Any,
    node: dict[str, Any],
    path: list[Any],
    by_span: dict[Any, dict[str, Any]],
    levels: dict[str, dict[str, Any]],
    kinds: dict[str, str],
) -> Block:
    """Return one statement as a block, with the lanes it owns."""
    kind = _kind(node)
    span = node.get("span")
    text = model.text_at(span) if span else ""
    step = by_span.get(span_key(span) or (0, 0, 0, 0), {})

    fields: list[dict[str, Any]] = []
    _fields(node, path, fields)
    test = node.get("test") if isinstance(node.get("test"), dict) else None
    found = model.trivia(list(span) if span else None)

    block = Block(
        path=list(path),
        kind=kind,
        role="step",
        text=text,
        label=_label(node, text),
        span=list(span) if span else None,
        plan=step.get("id", ""),
        fields=fields,
        condition=model.text_at(test["span"]) if test and test.get("span") else "",
        condition_span=list(test["span"]) if test and test.get("span") else None,
        note=found["text"],
        note_span=list(found["span"]) or None,
        note_where=found["where"],
    )

    if kind in ("FunctionDef", "AsyncFunctionDef") and node.get("name") in levels:
        entry = levels[node["name"]]
        block.role = "level"
        block.opens = entry["scope"]
        block.contains = entry["steps"]
        block.label = f"def {node['name']} ({entry['steps']})"
        return block

    if step:
        block.calls = str(step.get("callee") or "")
        opened = model.opens(step)
        if opened:
            block.opens, block.opens_module = opened[1], opened[0]
        block.resolved = _resolved(model, model.refers(step))

    if kind in LOOPS:
        block.role = "loop"
        block.lanes = [
            _lane(
                model,
                node.get(BODY_SLOT, []),
                [*path, BODY_SLOT],
                kinds.get(block.plan, "when_true"),
                by_span,
                levels,
                kinds,
            )
        ]
        return block

    if kind == "If":
        block.role = "branch"
        block.lanes = [
            _lane(model, node.get(slot, []), [*path, slot], name, by_span, levels, kinds) for name, slot in BRANCH_LANES
        ]
        return block

    block.role = _role(kind, block)
    return block


def _at(document: Any, path: list[Any]) -> Any:
    """Return the node a document path names."""
    for part in path:
        document = document[part]
    return document
