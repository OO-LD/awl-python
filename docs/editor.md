# Editor variants

Three canvases built against the same model, so what differs between them is
the paradigm and not the plumbing. Every shot below is taken inside the
Playwright test that asserts that state, at a fixed 1280x800 viewport, on the
same tier-2 procedure:

```python
def procedure(cycles: int) -> None:
    i = 0
    while i < cycles:
        charge(ChargeParam(target_voltage=4.2, c_rate=0.23))
        rest(600)
        i += 1
```

| Variant | Canvas | Form | wire | decoded | requests |
| --- | --- | --- | ---: | ---: | ---: |
| Blockly | Blockly | jedison | 420,355 | 1,715,546 | **9** |
| React Flow | React Flow | RJSF | 519,944 | 1,104,916 | 235 |
| React Flow + jedison | React Flow | jedison | **223,793** | **632,668** | 16 |

Fewest requests and most decoded bytes are the same fact about Blockly: one
Closure-compiled bundle with no dependency graph, so there is nothing to
flatten and nothing that could have been 235 round trips. Under JupyterLite
the round trips cost more than the bytes.

## The level

The procedure's five steps, and the loop.

<div class="grid" markdown>

<div markdown="1">
**Blockly**

![Blockly, the procedure level](assets/ui/blockly/01-level.png)
</div>

<div markdown="1">
**React Flow**

![React Flow, the procedure level](assets/ui/reactflow/01-level.png)
</div>

</div>

![React Flow with jedison, the procedure level](assets/ui/reactflow_jedison/01-level.png)

This is the whole comparison in one pair. Blockly wraps the body in a C-shape,
so what is inside the loop is inside the loop; it cannot draw `when_true` or
`repeat` at all, because its connections **are** the `next` edges. React Flow
draws `awl:repeat` as an explicit arc and answers "what repeats, and when does
it stop", but `i = 0` sits in the same column, the same indent and the same
style as the three steps inside the loop, with two edge labels the only thing
telling them apart.

Neither can do both. That is not a limitation either could fix.

Note also what each calls a statement. Blockly writes `i = 0` and
`while i < cycles:`; both React Flow variants write `CALL / i = 0`, because the
neutral vocabulary maps an assignment to a call. Correct in the graph, and
strange on a canvas.

## Where a typed parameter lives

All three answered this differently, which was not expected.

<div class="grid" markdown>

<div markdown="1">
**Blockly** puts the constructor in the call block, values visible.

![Blockly, the form](assets/ui/blockly/02-form.png)
</div>

<div markdown="1">
**React Flow** shows a node labelled only `ChargeParam`; the values need the panel.

![React Flow, the RJSF form](assets/ui/reactflow/02-form.png)
</div>

</div>

![React Flow with jedison, the form](assets/ui/reactflow_jedison/02-form.png)

React Flow with jedison gives the constructor its own node **carrying its
values**, which is the best of the three: the parameters are readable without
opening anything, and the form is still there when you want to edit them.

The `4,2` and `0,23` in some shots are Chromium formatting a number input from
its own UI locale, not the form library and not this project. It needs
`--lang=en-US` on the browser.

## After the edit

`target_voltage` set to 4.35 through the form, written back by span. One line
of the file changes and `c_rate=0.23` survives on it.

<div class="grid" markdown>

<div markdown="1">
**Blockly**

![Blockly, after the edit](assets/ui/blockly/03-edited.png)
</div>

<div markdown="1">
**React Flow**

![React Flow, after the edit](assets/ui/reactflow/03-edited.png)
</div>

</div>

![React Flow with jedison, after the edit](assets/ui/reactflow_jedison/03-edited.png)

## Descending into a call

Opening `charge` draws that function's own scope by the same rules. Nothing
counts depth: a level is a scope, and descending produces another scope.

<div class="grid" markdown>

<div markdown="1">
**Blockly**

![Blockly, the descended level](assets/ui/blockly/04-descended.png)
</div>

<div markdown="1">
**React Flow**

![React Flow, the descended level](assets/ui/reactflow/04-descended.png)
</div>

</div>

![React Flow with jedison, the descended level](assets/ui/reactflow_jedison/04-descended.png)

## The trace overlay

What actually ran, joined to the steps by span, which is the key the canvas was
drawn from. A loop body carries its iteration count.

<div class="grid" markdown>

<div markdown="1">
**Blockly**

![Blockly, the trace overlay](assets/ui/blockly/05-trace.png)
</div>

<div markdown="1">
**React Flow**

![React Flow, the trace overlay](assets/ui/reactflow/05-trace.png)
</div>

</div>

![React Flow with jedison, the trace overlay](assets/ui/reactflow_jedison/05-trace.png)

## Where to start

A module is imports and declarations, and the flow worth drawing is inside a
function, so both graph canvases opened at module scope and found nothing to
descend into. `EditorModel.scopes()` answers which levels a module offers, and
a `def` stays a declaration rather than becoming a step.

<div class="grid" markdown>

<div markdown="1">
**Blockly**

![Blockly, the level picker](assets/ui/blockly/00-scopes.png)
</div>

<div markdown="1">
**React Flow**

![React Flow, the level picker](assets/ui/reactflow/00-scopes.png)
</div>

</div>

## Two readings of a loop

Blockly is the only canvas that can nest, so it is the only one that had a
choice, and it built both.

<div class="grid" markdown>

<div markdown="1">
**Nested**: the body is in the loop.

![Blockly, the loop nested](assets/ui/blockly/06-loop-nested.png)
</div>

<div markdown="1">
**As a level**: the body is behind a click.

![Blockly, the loop as a level](assets/ui/blockly/07-loop-level.png)
</div>

</div>

The same procedure. Reading the loop as a level turns a two-statement body into
a navigation, and the descend gesture is already spent on functions. Nested
wins, and the pair is the argument.
