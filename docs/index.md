# awl-python
Python implementation of the [Abstract Workflow Language (AWL / AWL-LD)](https://github.com/OO-LD/awl-schema)

## Install

`pip install awl`

## Usage

```py
from awl import AstSerialization

ast_serialization = AstSerialization()

# python source code example
source = """if a == 1:
b = 1
else:
b = 'test'"""

# generate ast document
ast_dict = ast_serialization.parse(source)
print(ast_serialization.dumps())

# regenerate source code
src_code = ast_serialization.unparse(ast_dict)
assert src_code == source

# manipulate ast_dict: set b = 2
ast_dict["body"][0]["body"][0]["value"]["value"] = 2
src_code = ast_serialization.unparse(ast_dict)

assert src_code == """if a == 1:
b = 2
else:
b = 'test'"""

# export as json-ld
jsonld_doc = ast_serialization.to_jsonld()

# import into a graph
from rdflib import Graph
g = Graph()
g.parse(data=jsonld_doc, format="json-ld")

# dump graph as turtle
print(g.serialize(format="turtle"))

# query for all possible values of b
qres = g.query(
    """
    PREFIX awl: <https://w3id.org/awl/schema/>
    PREFIX ex: <https://example.org/>
    SELECT ?v
    WHERE {
        ?a a awl:Assign .
        ?a awl:HasTarget ex:b .
        ?a awl:HasValue ?v .
    }
    """
)

possible_values = [row[0].toPython() for row in qres]
assert possible_values == [1, "test"]
```
