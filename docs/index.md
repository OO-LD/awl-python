# awl-python

Python implementation of the [Abstract Workflow Language (AWL / AWL-LD)](https://github.com/OO-LD/awl-schema)

## Install

`pip install awl`

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

# The graph: the tree, the control-flow plan, the def-use edges and any
# typed member writes, in one store.
graph = pipeline.to_graph(source, module="example")
print(graph.serialize(format="turtle"))

# Which values can b take?
values = graph.query("""
    PREFIX awl: <https://w3id.org/awl/schema/>
    SELECT ?value WHERE {
      ?assign a awl:Assign ;
              awl:targets [ awl:id "b" ] ;
              awl:value [ awl:value ?value ] .
    }
""")
assert sorted(str(row[0]) for row in values) == ["1", "test"]

# Which definitions of b reach the end of the module? Asked of the def-use
# graph rather than of the syntax, so it survives a rename or a reorder.
definitions = graph.query("""
    PREFIX awl: <https://w3id.org/awl/schema/>
    SELECT ?definition WHERE { ?definition a awl:Definition ; awl:name "b" }
""")
assert len(list(definitions)) == 2
```

See [Examples](examples.md) for the same treatment applied to every file in the
validation corpus, source beside document beside RDF.
