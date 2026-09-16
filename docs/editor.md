# The editor

One Python procedure, edited as blocks and as source at the same time, with a
real run drawn over it.

`awl.ui.EditorModel` is the whole of it that matters here. It owns the
document, the edits and the source patches; a canvas supplies a drawing and a
form and nothing else. That split is not a convention, and
[the specification](editor-spec.md) records what happened each time it was
crossed.

```python
from awl import ui

model = ui.open_sample()
model.flow("procedure")["steps"]        # what to draw at one level
model.set_value(path, 4.35)             # a value, patched by span
model.run("procedure", 3, seconds=5.0)  # a real run, traced and bounded
model.to_source()                       # the file that comes out
```

## What was settled

Five canvases were built against this one model to answer two questions with
evidence rather than taste: whether a procedure reads better as nested control
flow or as a dataflow graph, and whether a typed parameter form belongs inside
a node or beside it.

Both are answered. Control flow needs **containment drawn as enclosure** and
**every edge read from the plan**, and the two are separable: implementations
shipped each without the other. Reading an edge from the plan and drawing it are
not the same requirement: a loop's `repeat` is read, recorded and not drawn,
because the region around the body already says the body repeats. The form
belongs **inside the node**, which was doubted until one implementation did it
with no side panel at all.

Only the canvas that won is kept, as `awl.ui.panel_reactflow`. The other four
were measured, reviewed and retired; what they taught is in the specification,
requirement by requirement, each with the failure that produced it. Keeping four
retired canvases to preserve that would be keeping the wrong artefact.

## Running it

In a notebook, or under `panel serve`:

```
python -m awl.ui.panel_reactflow --port 8104
```

It is a Panel application, so running it is starting a server. That is the cost
of the one canvas that could put the form inside the node; the specification's
last section carries the numbers.

## In a browser, with no install

Deployment is a separate concern and is not in this repository. The
[playgrounds repository](https://github.com/OO-LD/oold-playgrounds) builds this
editor into a static site with `panel convert`, alongside the OO-LD playgrounds,
and imports the editor from here rather than copying it.
