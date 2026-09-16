"""The pieces of the canvas that Panel has no widget for.

Everything else in this variant is an ordinary Panel object (the typed fields
inside a node are :class:`panel.widgets.FloatInput` and nothing more) and that
is the claim being tested. These are here because a gesture is not a value:

- :class:`BlockView` is what a node says and the things you can do to it, and it
  is where a **double-click** becomes a descent. ``panel-reactflow`` 0.4.1
  threads ``onNodeDoubleClick`` into its inner component and never passes one,
  so the library's canvas cannot report one; a node's own view can. It also
  carries the block's **comment**, which is the one thing about a statement the
  compact document cannot hold, because ``ast`` has no comment node.
- :class:`DropZone` is the strip between two statements. It knows the document
  path it would write into before anything is dropped on it, which is what lets
  it light up under the pointer rather than after the fact.
- :class:`Toolbox` is what you drag from. It drags with pointer events and not
  with HTML5 drag-and-drop, because the drop targets are inside shadow roots and
  because a pointer drag is what a test can perform the way a person does.
- :class:`SourcePane` is Monaco, with ty checking the Python inside it.
- :class:`Console` is what the last run said, at the bottom of the screen where
  there is room for it. A run produces output, a failure and a count per step,
  and a one-line notice can hold one of the three: the other two were dropped,
  including the output the procedure printed.
- :class:`Splitter` is the grip between the canvas and the source pane. A fixed
  split is a guess about which half the reader is working in.

None of them holds any editing semantics. Each sends one dict per gesture to the
editor, which turns it into a call on :class:`awl.ui.EditorModel`.
"""

from __future__ import annotations

from typing import Any, ClassVar

import panel as pn
import param

__all__ = [
    "CODICON",
    "MONACO",
    "QUIET",
    "BlockView",
    "Console",
    "DropZone",
    "LaneView",
    "SourcePane",
    "Splitter",
    "Toolbox",
]

#: The Monaco release this pane is pinned to.
MONACO = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2"

#: Monaco's icon font, which Monaco itself cannot load here.
#:
#: Its own rule is ``src: url("./codicon.ttf")``, relative to the *document*,
#: and the document is a Panel application served from ``/``: the browser asked
#: this server for ``/codicon.ttf``, got a 404, and every icon in the pane came
#: out as the notdef box. The reference build has the same rule and a bundler
#: that rewrote the path to a real asset; there is no bundler here, so the path
#: is written out in full against the same release the editor comes from.
CODICON = f"{MONACO}/esm/vs/base/browser/ui/codicons/codicon/codicon.ttf"

#: How long after the last keystroke the pane speaks to Python, in milliseconds.
#:
#: Everything the pane does per edit is in here, the type check included. Only
#: the round trip was debounced before, so ty checked the whole file on every
#: character and then wrote the count back through a synced parameter, which is
#: a round trip per keystroke by another name.
QUIET = 100

#: The drag every component on the canvas shares.
#:
#: A pointer drag rather than HTML5 drag-and-drop. The drop targets live in
#: separate shadow roots, one per Panel component, so ``elementFromPoint`` hands
#: back the host and ``dataTransfer`` is the wrong shape for a highlight that
#: has to follow the pointer. Every zone registers its own rectangle instead and
#: the drag hit-tests them itself, which is also the arrangement a test can
#: drive with the mouse the way a person does.
_DRAG = """
function drag() {
  if (!window.__awlDrag) {
    window.__awlDrag = { kind: '', label: '', zones: new Set(), armed: null, ghost: null }
  }
  return window.__awlDrag
}

function hit(state, x, y) {
  for (const zone of state.zones) {
    if (!zone.el.isConnected) { state.zones.delete(zone); continue }
    const box = zone.el.getBoundingClientRect()
    if (box.width && x >= box.left - 6 && x <= box.right + 6 && y >= box.top - 10 && y <= box.bottom + 10) {
      return zone
    }
  }
  return null
}

function arm(state, zone) {
  if (state.armed === zone) return
  if (state.armed) state.armed.el.classList.remove('awl-armed')
  state.armed = zone
  if (zone) zone.el.classList.add('awl-armed')
}
"""


class _Sending(pn.custom.JSComponent):
    """A component that hands one dict per gesture back to the editor.

    The callback is a plain attribute and deliberately not a parameter: every
    parameter of an ESM component is synced to the browser, and a callback is
    the editor's own method. Declaring one as ``param.Callable`` fails at the
    first render with ``unexpected attribute 'on_command'``, which is Bokeh
    saying the same thing less kindly.
    """

    __abstract = True

    def __init__(self, *, on_command: Any = None, **options: Any) -> None:
        super().__init__(**options)
        self.on_command = on_command

    def _handle_msg(self, data: Any) -> None:
        if self.on_command is not None:
            self.on_command(dict(data))


class BlockView(_Sending):
    """One statement, as the node says it: what it is, what it reads, what it does.

    The text is editable in place. A loop and a branch offer their *condition*,
    because the source a container covers is the whole loop and a one-line input
    over that would be a Python editor with extra steps; everything else offers
    the line it is. Both are written back by span through
    :meth:`~awl.ui.EditorModel.replace_at`, so a change that does not parse
    changes nothing and one that does costs the file's layout only in the range
    it replaces.

    It also says what the statement calls and what that name resolved to.
    ``resolved`` was collected and drawn nowhere, which left a call whose source
    was never indexed looking exactly like a call into an empty function, and
    those are different claims.

    Under both, the statement's **comment**, as the explanation it is. A comment
    is trivia and a span patch keeps trivia, so a note is written back exactly
    the way a literal is; what it must never take is the structural path, which
    regenerates the module and drops every comment in the file, including the
    one being edited.
    """

    kind = param.String(default="")
    text = param.String(default="")
    path = param.String(default="")
    role = param.String(default="step")
    opens = param.String(default="")
    calls = param.String(default="")
    resolved = param.String(default="")
    badge = param.String(default="")
    state = param.String(default="")
    note = param.String(default="")
    note_where = param.String(default="")
    notable = param.Boolean(default=False)
    multiline = param.Boolean(default=False)
    editable = param.Boolean(default=True)
    selected = param.Boolean(default=False)

    _esm = (
        _DRAG
        + """
export function render({ model, el }) {
  const root = document.createElement('div')
  root.className = 'awl-block'
  root.setAttribute('data-path', model.path)
  root.setAttribute('data-role', model.role)

  const head = document.createElement('div')
  head.className = 'awl-head'

  /* The chip is the block's grip. Dragging it onto a zone is a move, and a
   * move across two lists is what makes a loop's contents editable rather than
   * decorative: the same gesture takes a statement in and out again. */
  const chip = document.createElement('span')
  chip.className = 'awl-chip'
  chip.textContent = model.kind
  chip.title = 'drag to move this block'
  chip.setAttribute('data-grip', model.path)
  const state = drag()
  chip.addEventListener('pointerdown', event => {
    event.stopPropagation()
    chip.setPointerCapture(event.pointerId)
    const from = { x: event.clientX, y: event.clientY }
    let ghost = null

    /* The drag starts on movement, not on the press, and the press is never
     * `preventDefault`ed. Both matter: a grip that swallows the press swallows
     * the double-click with it, and a double-click on a block is how a level is
     * opened. */
    const move = moveEvent => {
      if (!ghost) {
        if (Math.abs(moveEvent.clientX - from.x) + Math.abs(moveEvent.clientY - from.y) < 5) return
        ghost = document.createElement('div')
        ghost.className = 'awl-ghost'
        ghost.textContent = model.text.split('\\n')[0].slice(0, 40)
        ghost.style.cssText =
          'position:fixed;z-index:9999;pointer-events:none;font:600 11px ui-monospace,monospace;' +
          'background:#0f172a;color:#fff;border-radius:5px;padding:3px 8px;'
        document.body.appendChild(ghost)
      }
      ghost.style.left = `${moveEvent.clientX + 12}px`
      ghost.style.top = `${moveEvent.clientY + 10}px`
      arm(state, hit(state, moveEvent.clientX, moveEvent.clientY))
    }
    const up = upEvent => {
      chip.removeEventListener('pointermove', move)
      chip.removeEventListener('pointerup', up)
      if (!ghost) return
      ghost.remove()
      const landed = hit(state, upEvent.clientX, upEvent.clientY)
      arm(state, null)
      if (landed) landed.move(model.path)
    }
    chip.addEventListener('pointermove', move)
    chip.addEventListener('pointerup', up)
  })
  head.appendChild(chip)

  /* A block that stands for a level shows its name and is not an input. Its
   * source is the whole function, and a one-line field over that is not an
   * escape hatch, it is a trap; the level is opened and edited inside. Making
   * it a plain label also leaves the whole block double-clickable, which is
   * how a level is opened. */
  const input = document.createElement(model.editable ? (model.multiline ? 'textarea' : 'input') : 'span')
  input.className = model.editable ? 'awl-text' : 'awl-text awl-text-static'
  if (model.editable) {
    input.spellcheck = false
    input.value = model.text
    input.setAttribute('data-edit', model.path)
  } else {
    input.textContent = model.text
  }
  head.appendChild(input)

  const badge = document.createElement('span')
  badge.className = 'awl-badge'
  head.appendChild(badge)

  /* What the call resolved to, or that it resolved to nothing. The open button
   * beside it already says the source can be read, so this is the difference
   * between the two things that button is absent for: a name that resolved to
   * something this canvas cannot descend into, and a name that resolved to
   * nothing at all. */
  const resolved = document.createElement('span')
  resolved.className = 'awl-resolved'
  resolved.setAttribute('data-testid', 'resolved')
  head.appendChild(resolved)

  if (model.opens) {
    const open = document.createElement('button')
    open.className = 'awl-open'
    open.title = `open ${model.opens}`
    open.setAttribute('data-open', model.path)
    open.textContent = '\\u203a'
    open.addEventListener('click', event => {
      event.stopPropagation()
      model.send_msg({ op: 'descend', path: model.path })
    })
    head.appendChild(open)
  }

  const remove = document.createElement('button')
  remove.className = 'awl-delete'
  remove.title = 'delete this block'
  remove.setAttribute('data-delete', model.path)
  remove.textContent = '\\u00d7'
  remove.addEventListener('click', event => {
    event.stopPropagation()
    model.send_msg({ op: 'delete', path: model.path })
  })
  head.appendChild(remove)

  root.appendChild(head)

  /* The statement's comment, on a line of its own under the header. Offered on
   * every block and not only on the ones that already carry a comment: a note
   * line that appears where a comment exists is a viewer, and a reader with
   * nothing to click cannot write the first one. */
  const note = document.createElement('input')
  note.className = 'awl-note'
  note.spellcheck = false
  note.placeholder = 'note'
  note.value = model.note
  note.setAttribute('data-note', model.path)
  const hash = document.createElement('span')
  hash.className = 'awl-hash'
  hash.textContent = '#'
  const notes = document.createElement('div')
  notes.className = 'awl-notes'
  notes.append(hash, note)
  if (model.notable) root.appendChild(notes)

  /* Committed against what was last sent, not against what the field started
   * with: typing and then pressing Enter fires `change` and `keydown` from one
   * edit, and an apply that compares with the original applies it twice: the
   * second call rewriting a span the first one moved. */
  let current = model.text
  const commit = () => {
    if (input.value === current) return
    current = input.value
    model.send_msg({ op: 'edit', path: model.path, text: input.value })
  }
  if (model.editable) {
    input.addEventListener('change', commit)
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !model.multiline) {
        event.preventDefault()
        commit()
      }
    })
  }

  let wrote = model.note
  const keep = () => {
    if (note.value === wrote) return
    wrote = note.value
    model.send_msg({ op: 'note', path: model.path, text: note.value })
  }
  note.addEventListener('change', keep)
  note.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    keep()
  })
  /* A click in the note is a click on the block, and the block reports its own
   * selection below, so the note must not also be read as a descent. */
  note.addEventListener('dblclick', event => event.stopPropagation())

  /* The library's canvas cannot report a double-click, so the node does.
   * A double-click inside an editable field selects a word and is left alone;
   * everywhere else on the block, including a level's own label, it opens. */
  root.addEventListener('dblclick', event => {
    if (model.editable && event.target === input) return
    if (model.opens) model.send_msg({ op: 'descend', path: model.path })
  })

  /* And the block reports its own selection, rather than leaving it to the
   * canvas. React Flow raises nothing when the block clicked is the one it
   * already holds. An insert moves the editor's selection somewhere React Flow
   * was never told about, and clicking back on this one then said nothing. */
  root.addEventListener('click', () => model.send_msg({ op: 'select', path: model.path }))

  const paint = () => {
    badge.textContent = model.badge
    badge.style.display = model.badge ? 'inline-block' : 'none'
    /* Just the word, because the name is already on the block a hand's width
     * to the left: writing it twice cost the mark enough room to be truncated
     * to `notify unreso...`, which is the one thing it must not say. */
    const unread = !model.resolved && !!model.calls
    resolved.textContent = model.resolved || (unread ? 'unresolved' : '')
    resolved.title = unread
      ? `${model.calls} resolved to nothing: its source was never indexed`
      : model.resolved && (model.calls && model.calls !== model.resolved
          ? `${model.calls} resolves to ${model.resolved}`
          : `resolves to ${model.resolved}`)
    resolved.classList.toggle('awl-unresolved', unread)
    resolved.style.display = resolved.textContent ? 'inline-block' : 'none'
    root.setAttribute('data-resolved', model.resolved)
    root.setAttribute('data-state', model.state)
    /* Never while it has the caret. Any parameter arriving mid-edit repaints
     * the block, and this line put the file's text back over what was being
     * typed: clicking into a field is itself a selection, so the round trip it
     * starts landed two keystrokes in and emptied the field. */
    if (model.editable) {
      if (!input.matches(':focus') && input.value !== model.text) { input.value = model.text; current = model.text }
    } else {
      input.textContent = model.text
    }
    if (!note.matches(':focus') && note.value !== model.note) { note.value = model.note; wrote = model.note }
    note.title = model.note_where === 'above'
      ? 'the comment on the line above this statement'
      : model.note_where === 'beside'
        ? 'the comment on this statement\\'s own line'
        : 'no comment yet: what is written here goes beside the statement'
    notes.setAttribute('data-where', model.note_where)
    chip.textContent = model.kind
  }
  /* The ring goes on the React Flow node, not on this element. This element is
   * only the block's header line; a block carrying typed fields shows a row of
   * them under it, in a column, and a ring drawn here stopped at the bottom of
   * the header and left that row outside it. The node is the one element that
   * is the whole block in both cases. */
  let holder = null
  const owner = () => {
    if (holder && holder.isConnected) return holder
    let at = el
    while (at) {
      if (at.classList && at.classList.contains('react-flow__node')) { holder = at; return at }
      at = at.parentNode instanceof ShadowRoot ? at.parentNode.host : at.parentNode
    }
    return null
  }

  /* The ring on its own, because it is the one thing that changes without the
   * block changing, and repainting everything to move it is what put the
   * paragraph above here. */
  const mark = () => {
    root.setAttribute('data-selected', model.selected ? '1' : '')
    const node = owner()
    if (node) node.toggleAttribute('data-awl-selected', model.selected)
  }
  model.on('badge', paint)
  model.on('state', paint)
  model.on('text', paint)
  model.on('calls', paint)
  model.on('resolved', paint)
  model.on('note', paint)
  model.on('note_where', paint)
  model.on('selected', mark)
  paint()
  mark()
  /* And again once the node exists. This view is built before the node holding
   * it does, so the walk above finds nothing on the pass that matters most: a
   * block that has just appeared is drawn already wearing the ring. */
  requestAnimationFrame(mark)

  el.classList.add('awl-block-host')
  return root
}
"""
    )

    _stylesheets: ClassVar[list[str]] = [
        """
/* One inset for the whole node, shared with the typed fields underneath, which
 * live in a Panel row in a shadow root of their own. Two hand-tuned paddings
 * put the fields three pixels off the header above them and let the second one
 * run past the node's right edge, and nothing in the DOM said so: the fields
 * are inside the node, which is this variant's whole claim, and a claim about
 * where something is has to be measured. */
:host { display: block; --awl-inset: 9px; }
.awl-block {
  font: 12px/1.35 ui-monospace, SFMono-Regular, Consolas, monospace;
  padding: 6px var(--awl-inset);
}
/* What was just inserted, and what the path bar is describing. The ring itself
 * is on the node, put there by this view: the canvas keeps its own idea of the
 * selection in the browser and overwrites what the editor sends for any node it
 * already has, so a ring set from Python appeared on nothing. */
.awl-block[data-selected="1"] { border-radius: 6px; }
.awl-head { display: flex; align-items: center; gap: 6px; }
.awl-chip {
  flex: 0 0 auto; font: 600 9px/1 ui-sans-serif, system-ui; letter-spacing: .04em;
  text-transform: uppercase; color: #475569; background: #e2e8f0; border-radius: 3px; padding: 3px 5px;
}
.awl-text {
  flex: 1 1 auto; min-width: 0; font: inherit; color: #0f172a; background: #f8fafc;
  border: 1px solid #e2e8f0; border-radius: 4px; padding: 3px 6px; resize: none;
}
.awl-text:focus { outline: 2px solid #6366f1; outline-offset: -1px; background: #fff; }
textarea.awl-text { height: 40px; }
.awl-text-static {
  background: transparent; border-color: transparent; font-weight: 600; cursor: pointer;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.awl-open, .awl-delete {
  flex: 0 0 auto; border: 1px solid #cbd5e1; background: #fff; color: #475569;
  border-radius: 4px; width: 20px; height: 20px; line-height: 1; cursor: pointer; padding: 0;
}
.awl-open { color: #4338ca; font-weight: 700; }
.awl-delete:hover { background: #fee2e2; border-color: #fca5a5; color: #b91c1c; }
.awl-notes { display: flex; align-items: center; gap: 5px; height: 22px; }
.awl-hash { flex: 0 0 auto; font: 700 11px/1 ui-monospace, monospace; color: #94a3b8; }
.awl-note {
  flex: 1 1 auto; min-width: 0; font: italic 11px/1.3 ui-sans-serif, system-ui;
  color: #475569; background: transparent; border: 0; border-bottom: 1px dotted transparent;
  padding: 2px 2px; outline: none;
}
.awl-note::placeholder { color: #cbd5e1; font-style: normal; }
.awl-note:hover { border-bottom-color: #cbd5e1; }
.awl-note:focus { border-bottom-color: #6366f1; background: #fff; color: #0f172a; }
.awl-notes[data-where="above"] .awl-hash { color: #6366f1; }
.awl-badge {
  flex: 0 0 auto; font: 600 10px/1 ui-sans-serif, system-ui; color: #fff; background: #16a34a;
  border-radius: 8px; padding: 3px 6px;
}
.awl-resolved {
  flex: 0 0 auto; min-width: 0; max-width: 34%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font: 500 10px/1.3 ui-monospace, monospace; color: #475569; background: #f1f5f9;
  border: 1px solid #e2e8f0; border-radius: 3px; padding: 2px 5px;
}
.awl-resolved.awl-unresolved { color: #92400e; background: #fef3c7; border: 1px dashed #f59e0b; }
[data-state="skipped"] .awl-chip { background: #f1f5f9; color: #94a3b8; }
[data-state="skipped"] .awl-text { color: #94a3b8; }
[data-state="skipped"] .awl-badge { background: #94a3b8; }
"""
    ]


class LaneView(_Sending):
    """A lane's label: what it is, and the plan's word for how control gets in.

    It carries a selection too, because a branch's ``then`` is a place to be
    standing and a nesting crumb names it. A lane is not a React Flow selection
    target, so a crumb for one had nowhere at all to point.
    """

    label = param.String(default="")
    kind = param.String(default="")
    selected = param.Boolean(default=False)

    _esm = """
export function render({ model }) {
  const el = document.createElement('div')
  el.className = 'awl-lane'
  const name = document.createElement('span')
  name.className = 'awl-lane-name'
  const kind = document.createElement('span')
  kind.className = 'awl-lane-kind'
  const paint = () => {
    name.textContent = model.label
    kind.textContent = model.kind
    kind.style.display = model.kind && model.kind !== model.label ? 'inline' : 'none'
    el.setAttribute('data-selected', model.selected ? '1' : '')
  }
  model.on('label', paint)
  model.on('kind', paint)
  model.on('selected', paint)
  paint()
  el.append(name, kind)
  return el
}
"""

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; }
.awl-lane { display: flex; gap: 6px; align-items: baseline; padding: 3px 8px; }
.awl-lane-name { font: 700 10px/1 ui-sans-serif, system-ui; letter-spacing: .06em; text-transform: uppercase; color: #4338ca; }
.awl-lane-kind { font: 500 10px/1 ui-monospace, monospace; color: #7c8db5; }
.awl-lane[data-selected="1"] {
  outline: 2.5px solid #4338ca; outline-offset: 1px; border-radius: 6px; background: #eef2ff;
}
"""
    ]


class DropZone(_Sending):
    """The strip a dropped block lands on, and the path it writes into.

    Before and after every statement in every list, including the empty ``else``
    of a branch, which is what makes what a container encloses editable rather
    than decorative. It knows its list and its index up front, so it can light
    up under the pointer while the drag is still running.
    """

    lane = param.String(default="")
    index = param.Integer(default=0)

    _esm = (
        _DRAG
        + """
export function render({ model, el }) {
  const zone = document.createElement('div')
  zone.className = 'awl-zone'
  zone.setAttribute('data-zone', `${model.lane}:${model.index}`)
  const rule = document.createElement('div')
  rule.className = 'awl-zone-rule'
  const tag = document.createElement('span')
  tag.className = 'awl-zone-tag'
  tag.textContent = 'drop here'
  zone.append(rule, tag)

  const state = drag()
  const entry = {
    el: zone,
    drop: () => model.send_msg({ op: 'insert', into: model.lane, index: model.index, kind: state.kind }),
    move: path => model.send_msg({ op: 'move', path, into: model.lane, index: model.index }),
  }
  state.zones.add(entry)
  el.classList.add('awl-zone-host')
  return zone
}
"""
    )

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; }
.awl-zone {
  position: relative; height: 18px; display: flex; align-items: center; justify-content: center;
  border-radius: 9px; border: 1px dashed transparent;
}
.awl-zone-rule { width: 100%; height: 2px; border-radius: 1px; background: transparent; }
.awl-zone-tag { position: absolute; font: 600 9px/1 ui-sans-serif, system-ui; color: #4338ca; display: none; }
.awl-zone.awl-armed { border-color: #6366f1; background: #eef2ff; }
.awl-zone.awl-armed .awl-zone-rule { background: #6366f1; }
.awl-zone.awl-armed .awl-zone-tag { display: block; background: #eef2ff; padding: 0 6px; }
"""
    ]


class Console(_Sending):
    """What the last run said, and anything that went wrong since.

    The bottom of the screen was empty and the whole of this was squeezed into
    a notice one line long, which can hold one sentence: a run produces output,
    a count per step and sometimes a failure, so two of the three were dropped
    every time. Anything a procedure prints had nowhere to go at all.

    A view and nothing else. Every line is written by the editor, which is where
    a run is started and where a gesture fails.
    """

    lines = param.List(default=[])

    _esm = """
export function render({ model, el }) {
  const root = document.createElement('div')
  root.className = 'awl-console'
  root.setAttribute('data-testid', 'console')
  const paint = () => {
    root.textContent = ''
    for (const entry of model.lines) {
      const line = document.createElement('div')
      line.className = 'awl-line'
      line.setAttribute('data-kind', entry.kind || 'said')
      line.textContent = entry.text
      root.appendChild(line)
    }
    /* Pinned to the newest line. A console that keeps its scroll shows the
     * start of the last run while the reader is looking for what just failed. */
    root.scrollTop = root.scrollHeight
  }
  model.on('lines', paint)
  paint()
  el.classList.add('awl-console-host')
  return root
}
"""

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; height: 100%; }
.awl-console {
  height: 100%; overflow: auto; padding: 4px 10px 8px;
  font: 11.5px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; color: #334155;
}
.awl-line { white-space: pre-wrap; word-break: break-word; }
.awl-line[data-kind="ran"] { color: #0f172a; font-weight: 700; margin-top: 4px; }
.awl-line[data-kind="out"] { color: #1e293b; }
.awl-line[data-kind="step"] { color: #475569; padding-left: 12px; }
.awl-line[data-kind="error"] { color: #b91c1c; font-weight: 600; }
"""
    ]


class Splitter(_Sending):
    """The grip between the canvas and the source pane.

    A fixed split is a guess about which half the reader is working in, and the
    guess is wrong for half of what an editor is for: reading a procedure wants
    the canvas, writing one wants the file. The drag reports the width the pane
    should have, and the pane's width is Python's, so the two halves cannot
    disagree about where the boundary is.
    """

    _esm = """
export function render({ model, el }) {
  const grip = document.createElement('div')
  grip.className = 'awl-splitter'
  grip.setAttribute('data-testid', 'splitter')
  const rule = document.createElement('div')
  rule.className = 'awl-splitter-rule'
  grip.appendChild(rule)

  let sending = 0
  grip.addEventListener('pointerdown', event => {
    event.preventDefault()
    grip.setPointerCapture(event.pointerId)
    grip.classList.add('awl-splitting')
    /* Reported as a width and not as a delta: a delta has to be added to
     * whatever Python currently thinks the width is, and a dropped message in
     * the middle of a drag then leaves the two ends of the drag disagreeing. */
    const report = at => model.send_msg({ op: 'split', width: Math.round(window.innerWidth - at) })
    const move = moveEvent => {
      const now = moveEvent.timeStamp
      if (now - sending < 60) return
      sending = now
      report(moveEvent.clientX)
    }
    const up = upEvent => {
      grip.removeEventListener('pointermove', move)
      grip.removeEventListener('pointerup', up)
      grip.classList.remove('awl-splitting')
      report(upEvent.clientX)
    }
    grip.addEventListener('pointermove', move)
    grip.addEventListener('pointerup', up)
  })
  el.classList.add('awl-splitter-host')
  return grip
}
"""

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; height: 100%; }
.awl-splitter {
  width: 7px; height: 100%; cursor: col-resize; background: #f1f5f9;
  border-left: 1px solid #e2e8f0; display: flex; align-items: center; justify-content: center;
  touch-action: none; user-select: none;
}
.awl-splitter:hover, .awl-splitter.awl-splitting { background: #e0e7ff; }
.awl-splitter-rule { width: 1px; height: 28px; background: #94a3b8; border-radius: 1px; }
"""
    ]


class Toolbox(_Sending):
    """What can be dropped, and the drag that carries it to a zone.

    Pointer events rather than HTML5 drag-and-drop: the zones are in shadow
    roots of their own, so the drag hit-tests the rectangles they registered
    instead of asking the document what is under the pointer.
    """

    entries = param.List(default=[])

    _esm = (
        _DRAG
        + """
export function render({ model, el }) {
  const root = document.createElement('div')
  root.className = 'awl-toolbox'
  const state = drag()

  const build = () => {
    root.textContent = ''
    for (const group of model.entries) {
      const title = document.createElement('div')
      title.className = 'awl-group'
      title.textContent = group.name
      root.appendChild(title)
      for (const item of group.items) {
        const button = document.createElement('div')
        button.className = 'awl-item'
        button.textContent = item.label
        button.title = item.code
        button.setAttribute('data-tool', item.kind)
        button.addEventListener('pointerdown', event => {
          event.preventDefault()
          button.setPointerCapture(event.pointerId)
          state.kind = item.kind
          state.label = item.label
          const ghost = document.createElement('div')
          ghost.className = 'awl-ghost'
          ghost.textContent = item.label
          ghost.style.cssText =
            'position:fixed;z-index:9999;pointer-events:none;font:600 11px ui-sans-serif,system-ui;' +
            'background:#4338ca;color:#fff;border-radius:5px;padding:3px 8px;'
          document.body.appendChild(ghost)
          state.ghost = ghost

          const move = moveEvent => {
            ghost.style.left = `${moveEvent.clientX + 12}px`
            ghost.style.top = `${moveEvent.clientY + 10}px`
            arm(state, hit(state, moveEvent.clientX, moveEvent.clientY))
          }
          const up = upEvent => {
            button.removeEventListener('pointermove', move)
            button.removeEventListener('pointerup', up)
            ghost.remove()
            state.ghost = null
            const landed = hit(state, upEvent.clientX, upEvent.clientY)
            arm(state, null)
            if (landed) landed.drop()
            state.kind = ''
          }
          button.addEventListener('pointermove', move)
          button.addEventListener('pointerup', up)
          move(event)
        })
        root.appendChild(button)
      }
    }
  }
  model.on('entries', build)
  build()
  el.classList.add('awl-toolbox-host')
  return root
}
"""
    )

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; }
.awl-toolbox { display: flex; flex-direction: column; gap: 4px; }
.awl-group {
  font: 700 9px/1 ui-sans-serif, system-ui; letter-spacing: .08em; text-transform: uppercase;
  color: #64748b; margin-top: 6px;
}
.awl-item {
  font: 500 12px/1 ui-sans-serif, system-ui; border: 1px solid #cbd5e1; border-radius: 5px;
  padding: 6px 8px; background: #fff; cursor: grab; user-select: none; touch-action: none;
}
.awl-item:hover { border-color: #6366f1; background: #eef2ff; }
"""
    ]


class SourcePane(_Sending):
    """The file in Monaco, type-checked by ty, in one pane.

    What it replaces. This was a transparent ``textarea`` over a coloured
    ``pre``, with Python's tokenizer painting the layer underneath. That
    arrangement works and costs nothing on the wire, and keeping the two layers
    in register cost a scroll transform, a caret guard and a rule about which
    element is allowed to scroll. It also cannot do anything a code editor does:
    no gutter, no diagnostics, no hover, no completion.

    What it is now. Monaco, loaded as ESM through an import map, which is the
    same mechanism the React Flow canvas arrives by and the one ``panel
    convert`` emits for a Pyodide build. ty is Astral's type checker compiled to
    WebAssembly; the host says where it lives and this drives it, so a name that
    does not type-check is underlined in the pane and hovering one says what it
    was inferred to be.

    Three decisions worth naming, because each of them is a cost avoided rather
    than a preference.

    **Not panelini's MonacoEditor.** That panel is built for JSON and YAML and
    its bundle says so: ``editor.all.js``, the JSON language service and the
    YAML contribution, and nothing else. A search of the shipped 6.7 MB module
    for ``elif`` or ``nonlocal`` finds neither, so ``language="python"`` renders
    a language Monaco has never heard of, with no highlighting at all, which is
    the exact failure this comparison already shipped once. It also exports only
    ``render``, so there is no ``monaco`` to register a grammar on, no way to
    set a marker and no way to add a hover provider.

    **A private language id.** Monaco registers ``python`` with a lazy loader,
    and jsDelivr rebundles that chunk whole: encountering the language costs a
    second 604 kB download of a grammar this page can fetch in 8 kB on its own.
    The grammar file is Monaco's, not one written here; only the id it is
    registered under is this editor's, which is also why ty's hover markdown has
    its fences rewritten before it is rendered.

    **The whole document, not the level.** A type checker needs the module, and
    the pane is the module, so the two agree without anything being spliced.
    """

    source = param.String(default="")
    goto = param.Integer(default=0)
    ty_url = param.String(default="")
    problems = param.List(default=[])
    marks = param.List(default=[])
    hints = param.Dict(default={})
    ready = param.Boolean(default=False)
    checked = param.Integer(default=-1)

    _importmap: ClassVar[dict[str, Any]] = {
        "imports": {
            "monaco-editor": f"{MONACO}/+esm",
            # An absolute key, which an import map is allowed and which is the
            # point: the grammar file below imports this path relatively, and
            # left alone the browser would fetch a second, unbundled copy of
            # Monaco to satisfy it.
            f"{MONACO}/esm/vs/editor/editor.api.js": f"{MONACO}/+esm",
            "monaco-python": f"{MONACO}/esm/vs/basic-languages/python/python.js",
        }
    }

    _esm = r"""
import * as monaco from "monaco-editor"
import { conf, language } from "monaco-python"

const CODICON = '__CODICON__'
const QUIET = __QUIET__
const LANGUAGE = 'awl-python'
monaco.languages.register({ id: LANGUAGE, extensions: ['.py'] })
monaco.languages.setLanguageConfiguration(LANGUAGE, conf)
monaco.languages.setMonarchTokensProvider(LANGUAGE, language)

/* Every pane on the page, by the text model it is editing, so the providers
 * below can be registered once and still answer for whichever pane asked. */
const panes = new Map()

/* ty fences its markdown as python, and rendering that would make Monaco
 * encounter the built-in language and fetch its lazily loaded grammar: 604 kB
 * for a grammar already registered above under this editor's own id. */
function refence(markdown) {
  return String(markdown || '').replace(/```python/g, '```' + LANGUAGE)
}

/* wasm-bindgen exposes some of ty's accessors as getters and some as methods,
 * and which is which has changed between builds. */
function read(target, key, ...rest) {
  const value = target[key]
  return typeof value === 'function' ? value.call(target, ...rest) : value
}

let starting = null

function checker(where) {
  if (starting) return starting
  const url = new URL(where, window.location.href).href
  starting = (async () => {
    const module = await import(/* webpackIgnore: true */ url)
    await module.default({ module_or_path: url.replace(/ty_wasm\.js.*$/, 'ty_wasm_bg.wasm') })
    return { module, workspace: new module.Workspace('/', module.PositionEncoding.Utf16, {}) }
  })()
  return starting
}

/* ty holds its own copy of the file and only sees what it is handed. The check
 * below runs when the typing stops, so between the last keystroke and that the
 * copy is out of date, and a question asked in the gap is answered about the
 * file as it was: typing `param.` and asking for its members returned the
 * module's globals, because the line the dot is on did not exist yet. */
function freshen(pane, text) {
  if (pane.ty != null) pane.ty.workspace.updateFile(pane.handle, text.getValue())
}

monaco.languages.registerHoverProvider(LANGUAGE, {
  provideHover(text, position) {
    const pane = panes.get(text)
    if (pane == null) return null
    freshen(pane, text)
    const parts = []
    /* What the editor already knows, first: which module and symbol a name
     * resolved to is this package's own answer and no type checker's. */
    const word = text.getWordAtPosition(position)
    const hint = word && pane.hints[word.word]
    if (hint) parts.push({ value: hint })
    if (pane.ty) {
      const hover = pane.ty.workspace.hover(
        pane.handle, new pane.ty.module.Position(position.lineNumber, position.column))
      if (hover != null) parts.push({ value: refence(read(hover, 'markdown')), isTrusted: true })
    }
    return parts.length ? { contents: parts } : null
  },
})

monaco.languages.registerCompletionItemProvider(LANGUAGE, {
  triggerCharacters: ['.'],
  provideCompletionItems(text, position) {
    const pane = panes.get(text)
    if (pane == null || pane.ty == null) return { suggestions: [] }
    freshen(pane, text)
    const found = pane.ty.workspace.completions(
      pane.handle, new pane.ty.module.Position(position.lineNumber, position.column))
    const word = text.getWordUntilPosition(position)
    const range = {
      startLineNumber: position.lineNumber, endLineNumber: position.lineNumber,
      startColumn: word.startColumn, endColumn: position.column,
    }
    const digits = String(Math.max(found.length - 1, 0)).length
    return {
      incomplete: true,
      /* ty ranks its own answers and Monaco sorts alphabetically, so without
       * this every completion list opens on `__annotations__`. */
      suggestions: found.map((entry, index) => ({
        label: entry.name,
        sortText: String(index).padStart(digits, '0'),
        kind: monaco.languages.CompletionItemKind.Variable,
        insertText: entry.insert_text ?? entry.name,
        detail: entry.detail,
        documentation: entry.documentation,
        range,
      })),
    }
  },
})

export async function render({ model, el }) {
  const host = document.createElement('div')
  host.className = 'awl-source'
  host.setAttribute('data-testid', 'source')
  el.appendChild(host)

  /* Monaco's icon font, at the document, where a font is registered: an
   * `@font-face` inside a shadow root is ignored, so the rules copied below can
   * name the family and only this can make it exist.
   *
   * Monaco's own rule is `src: url("./codicon.ttf")`, relative to the document,
   * and the document is a Panel application served from `/`: the browser asked
   * this server for `/codicon.ttf`, got a 404, and every icon in the pane came
   * out as the notdef box. The rule is corrected in place rather than
   * overridden by a second one, because two faces of one family are two things
   * `document.fonts.load` loads and the broken one stays broken. */
  for (const style of document.head.querySelectorAll('style')) {
    const face = style.textContent || ''
    if (!/@font-face/.test(face) || !/codicon\.ttf/.test(face)) continue
    style.textContent = face.replace(/url\((["']?)\.\/codicon\.ttf\1\)/g, 'url("' + CODICON + '")')
  }

  /* Monaco writes its stylesheet into `document.head`, and a Panel component
   * renders into a shadow root, which does not see it: unadopted, the editor
   * draws as a column of unstyled text with the caret somewhere else. */
  const root = el.getRootNode()
  if (root.adoptedStyleSheets) {
    const sheets = []
    for (const style of document.head.querySelectorAll('style')) {
      const text = style.textContent || ''
      /* `codicon` as well as `monaco-editor`. Monaco writes about a hundred
       * style elements, one per module, and the one carrying the icon font
       * never says `monaco-editor` at all: every icon in the pane inherited
       * the editor's monospace family and drew the notdef box. */
      if (!/monaco-editor|codicon/.test(text)) continue
      const sheet = new CSSStyleSheet()
      sheet.replaceSync(text)
      sheets.push(sheet)
    }
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, ...sheets]
  }

  const text = monaco.editor.createModel(model.source, LANGUAGE)
  const view = monaco.editor.create(host, {
    model: text,
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 12,
    lineHeight: 18,
    /* The hover and suggest widgets are positioned against the editor, and the
     * pane is 420 px of a three column shell, so without this every one of them
     * is clipped by the column it lives in. */
    fixedOverflowWidgets: true,
    tabSize: 4,
  })
  /* Monaco's mouse-leave monitor asks `viewDomNode.contains(event.target)` on a
   * document listener, and inside a shadow root the event has already been
   * retargeted to the host, so the answer is always no: every mouse move was
   * read as leaving the editor and cancelled the hover that was about to open. */
  host.addEventListener('mousemove', event => event.stopPropagation())

  const pane = { hints: model.hints || {}, ty: null, handle: null }
  panes.set(text, pane)

  let applying = false
  let pending = null
  let decorations = null

  const check = () => {
    if (pane.ty == null) return
    pane.ty.workspace.updateFile(pane.handle, text.getValue())
    const found = pane.ty.workspace.checkFile(pane.handle)
    monaco.editor.setModelMarkers(text, 'ty', found.map(entry => {
      let at = null
      try { at = read(entry, 'toRange', pane.ty.workspace) } catch (error) { at = null }
      if (at == null) { try { at = read(entry, 'range') } catch (error) { at = null } }
      return {
        startLineNumber: at ? at.start.line : 1,
        startColumn: at ? at.start.column : 1,
        endLineNumber: at ? at.end.line : 1,
        endColumn: at ? at.end.column : 1,
        message: String(read(entry, 'message') || ''),
        code: String(read(entry, 'id') || ''),
        severity: monaco.MarkerSeverity.Error,
      }
    }))
    model.checked = found.length
  }

  /* The editor's own answer, kept under a name of its own: ty says whether the
   * file type-checks and this says whether it parses, and only the second one
   * decides whether the canvas is redrawn. */
  const complain = () => {
    monaco.editor.setModelMarkers(text, 'awl', (model.problems || []).map(entry => ({
      startLineNumber: entry.line || 1,
      startColumn: entry.column || 1,
      endLineNumber: entry.line || 1,
      endColumn: (entry.column || 1) + 1,
      message: entry.message,
      severity: monaco.MarkerSeverity.Error,
    })))
  }

  /* What the last run observed, written at the end of the line it happened on.
   * The same overlay the blocks wear, joined on the same spans, so the two
   * panes agree about which statement ran how often. */
  const overlay = () => {
    const wanted = (model.marks || [])
      .filter(mark => mark.line >= 1 && mark.line <= text.getLineCount())
      .map(mark => ({
        range: new monaco.Range(mark.line, text.getLineLength(mark.line) + 1,
                                mark.line, text.getLineLength(mark.line) + 1),
        options: {
          after: { content: '    ' + mark.text, inlineClassName: 'awl-ran' },
          hoverMessage: mark.detail ? [{ value: mark.detail }] : undefined,
          showIfCollapsed: true,
        },
      }))
    if (decorations == null) decorations = view.createDecorationsCollection(wanted)
    else decorations.set(wanted)
  }

  /* Nothing leaves the pane while the reader is still typing. A keystroke that
   * parses rebuilds every node on the canvas, and ty reads the whole module to
   * answer, so one of each per character makes the pane the slowest thing on
   * the page. The check used to run outside this and wrote its count back
   * through a synced parameter, which is a round trip per keystroke wearing a
   * different name. */
  const settled = () => {
    check()
    model.send_msg({ op: 'source', text: text.getValue() })
  }
  text.onDidChangeContent(() => {
    if (applying) return
    if (pending) window.clearTimeout(pending)
    pending = window.setTimeout(settled, QUIET)
  })

  model.on('source', () => {
    if (model.source === text.getValue()) return
    applying = true
    /* An edit rather than `setValue`, so the undo stack, the caret and the
     * scroll position all survive the round trip the canvas starts. */
    view.executeEdits('awl', [{ range: text.getFullModelRange(), text: model.source }])
    applying = false
    check()
    overlay()
  })
  model.on('goto', () => { if (model.goto) view.revealLineInCenter(model.goto) })
  model.on('problems', complain)
  model.on('marks', overlay)
  model.on('hints', () => { pane.hints = model.hints || {} })

  complain()
  overlay()
  model.ready = true

  if (model.ty_url) {
    try {
      pane.ty = await checker(model.ty_url)
      pane.handle = pane.ty.workspace.openFile('/module.py', text.getValue())
      check()
    } catch (error) {
      /* A pane that edits and reparses is the requirement; type checking is
       * what it gained. Losing the second must not cost the first, so the
       * failure is reported as a count of minus one and nothing else changes. */
      model.checked = -1
      console.warn('awl: ty did not start', error)
    }
  }

  return () => {
    panes.delete(text)
    if (pending) window.clearTimeout(pending)
    view.dispose()
    text.dispose()
  }
}
""".replace("__CODICON__", CODICON).replace("__QUIET__", str(QUIET))

    _stylesheets: ClassVar[list[str]] = [
        """
:host { display: block; height: 100%; }
.awl-source { width: 100%; height: 100%; }
.awl-ran { color: #15803d !important; font-weight: 700; }
"""
    ]
