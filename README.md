[![DOI](https://zenodo.org/badge/957336610.svg)](https://doi.org/10.5281/zenodo.15108186)
[![PyPI-Server](https://img.shields.io/pypi/v/awl.svg)](https://pypi.org/project/awl/)
[![codecov](https://codecov.io/gh/OO-LD/awl-python/branch/main/graph/badge.svg)](https://codecov.io/gh/OO-LD/awl-python)
[![Docs](https://img.shields.io/badge/docs-oo--ld.github.io-1f6feb)](https://oo-ld.github.io/awl-python/)

# awl-python

Python implementation of the
[Abstract Workflow Language (AWL / AWL-LD)](https://github.com/OO-LD/awl-schema).

A procedure written in Python is a file you run. This turns it into a document
you can also query and edit: what the code says, how control moves through it,
what each name refers to, which typed member a value was written to, and where
that value came from, in one graph.

Nothing is inferred from source text. A loop is found by its back edge, not by
matching `while`; a call is resolved to an identity, not to a spelling.

## Install

```bash
pip install awl
```

Python 3.11 or newer. The editor is an extra: `pip install "awl[editor]"`.

## Usage

```py
import ast

from awl import compact, pipeline

source = """if a == 1:
    b = 1
else:
    b = 'test'
"""

# The editor model: one node per statement, literals inline.
doc = pipeline.to_compact(source, module="example")
print(compact.dumps(doc))

# It regenerates the source it came from.
regenerated = ast.unparse(ast.fix_missing_locations(compact.decode(doc)))
assert regenerated == ast.unparse(ast.parse(source))

# Edit it: b = 2 in the true branch.
doc["body"][0]["body"][0]["value"] = {"literal": 2}
assert "b = 2" in ast.unparse(ast.fix_missing_locations(compact.decode(doc)))

# The graph: the same document, plus the control-flow plan, the def-use edges
# and any typed member writes, in one store.
graph = pipeline.to_graph(source, module="example")

# Which values can b take?
values = graph.query("""
    PREFIX awl: <https://w3id.org/awl/schema/>
    SELECT ?value WHERE {
      ?assign a awl:Assign ;
              awl:targets [ awl:var "b" ] ;
              awl:value [ awl:literal ?value ] .
    }
""")
assert sorted(str(row[0]) for row in values) == ["1", "test"]
```

RDF is not a second derivation of the source. It is the same document in
another notation, so the JSON and the graph cannot disagree.

## Profiles

A profile is a named set of generator parameters: which wrappers are
transparent, which types go opaque, whether keywords fold, which lookups run,
and whether the document carries spans, orderings, statement identities and the
comments written about them.

```py
from awl import pipeline

source = "def run(n):\n    while n:\n        n -= 1\n"

# The tree alone: what was written.
tree = pipeline.to_document(source, module="example", layers=("document",))

# The tree and how control moves through it. A statement carries the identity
# the plan mints for it, so a step and the statement it came from are one node
# rather than two matched by line and column.
both = pipeline.to_document(source, module="example", layers=("document", "plan"))
assert len(both["@graph"]) > len(tree["@graph"])
```

[Flavours](https://oo-ld.github.io/awl-python/flavours/) shows one procedure
under every setting, each with the SPARQL it answers and the answer computed at
build time, so a query that stops working stops appearing there.

## The editor

A procedure edited as blocks and as source at the same time, run for real under
a tracer, with the trace drawn over the steps that ran.

```bash
pip install "awl[editor]"
python -m awl.ui.panel_reactflow --port 8104
```

It also runs with no install at all, in a browser, through Pyodide:
[**open the playground**](https://oo-ld.github.io/oold-playgrounds/awl/).

Five canvases were built against one shared model to settle what an editor of
this kind has to do. Only the one that won is kept; what the other four taught
is written down in the
[editor specification](https://oo-ld.github.io/awl-python/editor-spec/),
requirement by requirement, each with the failure that produced it.

## Documentation

<https://oo-ld.github.io/awl-python/>

## Development

```bash
git clone https://github.com/OO-LD/awl-python
cd awl-python
make install          # uv sync plus the pre-commit hooks
make ci               # what CI runs: check, docs-test, test
```

`make help` lists the rest. The browser tests need
`uv run playwright install chromium`.
