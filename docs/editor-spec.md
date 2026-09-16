# Editor specification

What an AWL-LD editor must do, written from five implementations and four
independent reviews rather than from taste. Every requirement below is followed
by the failure that produced it: each one is a mistake something already made.

The implementations are not in this repository. They were built against
`awl.ui.EditorModel` to settle two design questions with evidence, and what they
settled is written down here; the one that won lives in its own playground. So
the failures below are attributed to "one implementation" rather than by name,
because naming a thing a reader cannot open is a reference to nothing.

The editor targets **procedures**. Value provenance is rendered and never
edited, so nothing here describes editing a def-use graph.

---

## 1. The model is shared; a canvas supplies a canvas

`awl.ui.EditorModel` owns the document, the edits and the source patches. A
canvas supplies a drawing and a form, and nothing else.

| It offers | For |
| --- | --- |
| `flow(scope)` | one level: `steps`, `edges`, `sublevels` |
| `sublevels(scope)`, `opens(step)`, `refers(step)`, `descend(step)` | navigation |
| `apply(op, **kw)` over `OPERATIONS` | add, delete, reorder, set a literal |
| `set_value(path, value)` | a value, written back by span |
| `text_at(span)`, `replace_at(span, text)` | a block edited through its source |
| `set_source(text)` | the source pane |
| `run(entry, *args)` | a real run, traced |
| `to_source()`, `reformats()`, `regenerate()` | producing the file |

**Why this is a requirement, not a convention.** One implementation added 206
lines to the shared model in its own worktree and competed against a model the
others did not have. Three defects, a collapsed node with no span, two edits
over one constructor raising, and `set_literal` destroying the span it replaced,
were found *only* because several canvases used the same model. A canvas that
reimplements edit semantics measures its own reimplementation.

---

## 2. A level is a scope, and every level is drawn the same way

Two sequential calls read as `a` then `b`. A conditional or a loop is a step of
its own between them, carrying `when_true`, `when_false`, `repeat`, `each_item`,
`exhausted` or `on_error` out of it.

Recursion is unlimited because nothing counts depth: a scope is a name, and
descending produces another scope.

---

## 3. Containment must be visible, and it must come from the plan

This is the finding the whole comparison produced, and the two halves are
separable.

**Containment.** What is inside a loop must be distinguishable from what follows
it, without inference. On a pure graph canvas, eleven steps sit at one indent and
two edge labels are the only thing separating inside from after. Reviewers
confirmed this reads as "what repeats" but not "what is in this loop".

**Every edge must come from the plan.** Read them from `flow(scope)["edges"]`,
never from the shape of a container. One implementation keyed its arc on
`classList.contains('sqd-step-container')` and was rejected: a shape-keyed arc
cannot tell a loop from a container that happens to look like one, and at module
scope it drew an arc where the plan reports none.

**The loop's repetition is expressed by the container, not by an arc.** The
region already encloses the body, so a `repeat` drawn as well says the same
thing twice, dashed, across the whole height of the loop and through a gutter
kept empty for it. An earlier revision of this section required the arc; a
person using the editor asked for it to go, and it went. What does not go is
where the fact comes from: the canvas still reads the `repeat` out of
`flow(scope)["edges"]`, records which block it leaves, and is tested on that.
**The plan edge is still what proves it, with a test rather than an arc**: a
canvas that stopped reading `repeat` and simply drew nothing would look
identical and would fail that test.

**An edge that leaves a container is drawn from the container.** Two of them
onto one target are one connector: the last statement of a `then` reaches the
statement after the `if` by the same door the `if` does, and drawing both is one
journey drawn twice. It is also the only way to get the arrowhead right where
the layout inherits `Position.Left`/`Position.Right` handles, since the vertical
leg of a step path lands half way between the two anchors and two anchors at
different indents end the path in a sideways stub across the top of the block it
arrives at.

**A branch is two lanes, not two labels.** `then` and `else` laid side by side
and rejoining below. When the `if` has no `else`, the empty lane is still drawn,
because it is where a statement is dropped to make one, and it is what
`when_false` names: the plan sends `when_false` past an `if` that has no `else`,
which is true of the source and reads as a mislabelled arrow beside an `else`
column the canvas has drawn anyway.

**Containment and the edges are separable, and each was shipped without the
other.** One canvas nested statements natively and could not draw the back edge
at all; another drew every edge and enclosed nothing.

**Do not reuse the descend gesture for a loop.** One implementation built both
and argued against it: reading a loop as a level turns a two-statement body into
a navigation, and the gesture is already spent on functions.

---

## 4. Every block is editable, removable and addable

Including `while`, `if`, `return` and bare assignments, not only calls with a
typed parameter object.

**All four of the first implementations failed this**, in the same way: only
value-carrying nodes got an editor. Measured, at one level: 0 of 16 canvas texts
editable in one, 5 of 11 steps in another, 3 of 11 in a third.

**A form over an arbitrary expression is a Python editor with extra steps.**
Edit those blocks through the source they cover, with `replace_at(span, text)`.
It reparses like any other edit, so a typo costs nothing.

**A control structure's editable range is its test**, not its span: a `while`
spans its whole body.

---

## 5. Where the typed parameter form lives

**Solved: inside the node.** The fifth implementation puts two `FloatInput`s in
the node itself and has no side panel at all, verified geometrically, and
editing one changes a single line while the sibling field survives.

One nuance worth carrying: the fields hang off the *assignment's* node rather
than a `ChargeParam` node of its own, which is the nested-block answer rather
than the constructor-as-a-node answer.

**Take the declared type, not the value's.** That implementation infers the
widget from the value, so `target_voltage=4` renders an integer input for a
field declared `float`. The class already says what it is.

The four earlier implementations put the form **beside** the node, because the
schema-form libraries render full-width labelled inputs and a node sized for
those stops being a node. Two partial answers came out of it, both worth
keeping:

- plugging the constructor into the call block, so its values are readable
  without opening anything;
- giving the constructor **its own node carrying its values**, which was the
  best of the four: readable at rest, editable on click.

The schema comes from the class's declared fields. Do not hand-author it, and do
not infer types from values when the declaration is reachable. One
implementation silently fell back to inference because it read only imported
modules and the sample declares its classes locally.

---

## 6. Navigation: levels and the nesting stack

The path bar carries the full stack, containers included, each crumb scoping the
canvas:

```
awl.ui.sample > procedure > while i < cycles: > if peak > report.peak_voltage: > then
```

**Module scope needs its own answer.** A module is imports and declarations, and
a `def` is not a step, so a canvas drawing what runs finds nothing to click.
`flow(scope)["sublevels"]` gives a block per level below, with its step count.
Two implementations independently dead-ended here before it existed.

**A call that resolves is not the same as a call that opens.** `opens()` returns
`None` both for an unresolved name and for a resolved class, so use `refers()`
to tell them apart. One implementation labelled `Report(...)` "source not read"
when it had resolved perfectly well and simply is not a level. A call whose
source was never indexed must be marked as such, not drawn as a leaf: an unread
function and an empty one are different claims.

---

## 7. Insertion: predefined blocks and honest drop targets

The toolbox offers at least `while`, `if`, an assignment and a return, as
templates, not only calls.

- **A placed loop is `while False:`, not `while True:`.** It reaches the canvas
  before its condition does, and the run button is one click away. One palette
  offered `while i < 10:`; dropped into a body that never touches `i` and run,
  it took the whole process down and needed a restart.
- **Bound the run.** An editor runs code nobody has read, so `run()` takes a
  `seconds` deadline and stops through the tracer, which is already on every
  line. What ran before the deadline is still reported.
- **Never offer nonsense.** One palette listed `dataclass()`, a name the module
  only ever decorates with, and `procedure(0)`, unbounded recursion into the
  level you are standing on.
- **A drop needs a target.** A curve between two nodes is not a slot; dropping on
  one means guessing which end was meant. Either draw snap zones before and after
  each node, or hang the gesture off the node where "after this" has one reading.
- **An insert must give feedback**: select what was placed and open its editor.
  One canvas reported a successful insert while selecting nothing, because its
  node sync discarded the selection flag for every id it already held and an
  insert renumbers paths rather than minting one.
- **A refused drop must leave nothing behind.** One implementation appended the
  block and then deleted it on refusal: two cancelling structural patches that
  `to_source()` cannot see cancel, so the file was intact but the next value edit
  anywhere would have regenerated the whole module.

---

## 8. Reorder is not an index

A statement list holds docstrings and declarations that are not steps, so
position in the list is not position in the flow.

**Offer the step it lands beside**, "move after `i += 1`", and disable it at the
ends. One implementation used a raw index: it moved an import below a class with
*zero* canvas change, and the module then raised
`NameError: name 'dataclass' is not defined` while the notice said "reorder
applied".

Refuse any move that crosses something undrawn, or that touches a declaration.
Three implementations made this same mistake independently, which is the
strongest evidence in this document that the rule is not obvious.

---

## 9. Undo goes through the model or does not exist

A canvas library's own undo restores its own nodes and does not touch Python.
After one such undo the canvas showed 11 blocks against a 10-statement file, and
every later edit addressed the previous version: the form for one path reported
a different statement.

Snapshot per edit and undo through `set_source`, or remove the control.

---

## 10. The source pane

Rendered, highlighted, editable, and bidirectional.

- **Whoever highlights must actually know Python.** Two implementations shipped
  a pane that coloured nothing, in the same way and for different libraries: one
  loaded CodeMirror with a `?deps=` pin that omitted `@codemirror/language`, so
  a second copy made the highlighter walk an empty tree, **229 KB and 38
  requests for no highlighting at all**; the other was offered an editor bundle
  carrying only the JSON and YAML contributions, where `language="python"` names
  a language the editor was never told about. Grep the bundle for `elif` before
  trusting it. Assert on **computed colours**, not on class names: a keyword and
  a plain name must differ.
- **Two honest ways to highlight, and the choice is a trade, not a default.**
  Python-side `tokenize` is already in the interpreter and costs nothing on the
  wire, but the coloured HTML then travels on every gesture, measured at 13,263
  bytes per interaction. A real editor component costs 854 KB once and nothing
  per gesture, and it is the only path to the next item.
- **A type checker in the pane is worth what it costs, and it costs a lot.**
  Diagnostics, hover and completion over the same file the blocks are drawn from
  were delivered by compiling a checker to WebAssembly: a red underline carrying
  the checker's own message, an inferred type on hover, and completion offering
  a field only a checker could know. The price is **17.8 MB** of WebAssembly, six
  times the whole editor. Price it separately and make it optional: with no
  checker the pane must still edit, highlight, round-trip and report a parse
  error.
- **The whole pane must be clickable.** A `position:absolute; inset:0` textarea
  covers only the visible portion of a scrolled document: the entire function on
  screen was unclickable, and only the top third took a caret.
- **Scroll to the level being edited.** Opening at the top of the file shows the
  module docstring at every level, which reads as "the highlighting is broken"
  when it is one long string token.
- **Typing must not strip the colours**, and the caret must not desynchronise
  from the coloured layer. Drag the coloured layer with a transform rather than a
  second `scrollTop`: a textarea and a `pre` disagree about `scrollHeight` by the
  vertical padding and drift apart at the bottom.
- **A repaint must not eat what is being typed.** Any state arriving mid-edit
  that rewrites the field's value from the model discards the keystrokes since
  the last sync; guard on focus.
- **A parse failure changes nothing**: a half-typed edit is the normal state of a
  source pane.

---

## 11. Running and the trace overlay

The run button performs a real run under instrumentation. Draw both of the
things the overlay carries: **iteration counts** and **branch outcomes**.

- The host supplies the entry point and any stand-in modules. A stand-in for a
  module that drives hardware is an object, and no JSON channel carries one.
- **A run that raises still returns the overlay**: a step that raised is a fact
  about the procedure. The same holds for a run stopped by its deadline.
- **A level the trace never reached is not a level that did not run.** Grey
  nothing when nothing was observed, and say so.
- **Clear the overlay on any structural or source edit.** Marks keyed on
  positional step ids survive a reparse and then name the wrong steps: after one
  insert, `while i < cycles` claimed 3 iterations and `return report` claimed it
  never ran.
- Name the level as well as the entry: `ran procedure: 4/5 steps in charge`.

---

## 12. Write-back has two tiers, and they are not equal

| Edit | Mechanism | Cost |
| --- | --- | --- |
| a literal, a constructor field, a block's source line | patch by span | one line changes; comments and layout survive |
| add, delete, reorder | regenerate the module | **comments and layout are lost** |

`reformats()` says in advance which path the next `to_source()` takes, so a
canvas can warn rather than a reader finding it in a diff. **Compute it and draw
it**: one implementation computed it on every structural edit and rendered it
nowhere, so an insert silently took nine blank lines out of the module while the
notice said only "added". Closing the gap needs a concrete-syntax rewrite, which
is not built.

**A value edit must not destroy its own address.** Preserve the span when
replacing a literal, and coalesce patches over one range: editing one thing twice
is the last one winning, not an overlap error. Insertions still stack, so two
zero-width inserts at one offset are two steps.

---

## 13. Identity does not survive an edit

Step identities are positional counters. Inserting a line anywhere earlier
renumbers everything after it: an edit inside `settle` renamed **10 of the 11**
steps in `procedure`, and `step#12` stopped being an `Assign` and became an
`Expr`.

Sound within one snapshot, which is all the plan mints them for. **Not enough for
an editor**: a selection, an overlay mark or a stored annotation keyed on a step
IRI is wrong after any edit, and two graphs of one file taken either side of an
edit cannot be joined even where the statements are untouched.

Until the identity contract changes, address by **document path** and by **scope
name**, not by step id, for anything that must outlive an edit.

---

## 14. Testing

- **Click and type like a person.** `locator.fill()` sets a value without ever
  placing a caret. Three implementations passed their source-pane tests while the
  pane was unusable by hand; the fill bypassed exactly the broken part.
- **Assert on computed style when appearance is the requirement.** One
  implementation's stylesheet never reached the component it was written for,
  and every assertion on class names passed anyway: a refusal rendered in the
  same grey as a success.
- **Take screenshots inside the test that asserts the state.** A screenshot taken
  separately can drift from what was verified. Check no two are byte-identical:
  two implementations shipped duplicate shots, and one showed the module level
  under the name `09-sublevel`.
- **Verify the rendered HTML, not the markup you generated.** A tab can fail to
  render while the assertion on the source passes.
- **Measure bytes after the page settles.** Summing inside `page.on("response")`
  undercounts randomly, 141k/165k/196k across runs of one page, because a
  response's size is known only once its body lands. Report **wire, decoded and
  request count** separately, and say whether the harness inlines its own assets:
  one did, and its "5.7 times cheaper" was really 2.58.
- **A suite that passes under load is the only one that passes.** One suite was
  green in isolation and lost one to three Playwright waits whenever other
  servers were running. Run it more than once before calling it green.

---

## 15. Weight

Requests matter more than bytes under JupyterLite: no bundler means one request
per module.

Measured across the canvases, wire cost spanned **87 KB to 766 KB** and request
count **6 to 269**, for the same procedure and the same model.

The library names are kept below because the cost is a fact about the library
rather than about the implementation that chose it.

| Canvas and form | wire | decoded | requests |
| --- | ---: | ---: | ---: |
| Sequential Workflow Designer | 86,748 | 275,754 | 6 |
| React Flow with jedison | 263,493 | 684,707 | 19 |
| Blockly with jedison | 450,536 | 1,745,727 | 9 |
| React Flow with RJSF | 766,048 | 1,620,990 | 269 |

The spread is mostly transitive dependencies rather than the canvases: RJSF's
validator chain pulls **lodash and lodash-es together, 431 KB of the same library
twice**, because `@rjsf/utils` imports from each. Pin every CDN import's
dependencies, but never React's own, which redirects React to a second copy of
itself and dies on a null hook dispatcher.

Only the first row has been re-derived since its canvas's fixes; the rest are
their builders' figures and the methods differ slightly.

**The canvas that was kept is off this table by an order of magnitude, and the
table would flatter it to include.** Measured the same way:

| | wire | requests |
| --- | ---: | ---: |
| shell: Panel, Bokeh, the canvas and the app | 3,355,196 | 34 |
| the editor component | 854,543 | 2 |
| the type checker, as WebAssembly | 17,813,412 | 2 |
| total | **22,023,151** | 38 |

2.88 MB gzipped. Three things follow, and they are the reason this is reported
in parts rather than as one number:

- **The comparison does not hold across these rows.** The four above load
  unbundled ES modules from a CDN that compresses everything; this one is a
  pip-installed wheel with its JavaScript already built, served by a development
  server that compresses only part of what it sends. Decoded equals wire
  wherever nothing is compressed, which is why gzipped is the only figure worth
  putting beside the others.
- **The IDE is most of the weight and none of the editor.** Report the checker
  separately, so dropping it is a decision someone can make.
- **A runtime is not a canvas.** 87% of the shell is Bokeh and Panel, and it
  buys a server requirement: this one needs a Bokeh server or Pyodide, where the
  other four run in a notebook cell with a kernel of any kind. That is the price
  of the form living inside the node, and it is worth stating next to the
  finding rather than in a footnote.
