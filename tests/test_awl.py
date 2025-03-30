from awl import AstSerialization


def test_ast_generation():
    ast_serialization = AstSerialization()
    source = """if a == 1:
    b = 1
else:
    b = 'test'"""

    ast_dict = ast_serialization.parse(source)
    # print(json.dumps(ast_dict, indent=4))
    print(ast_serialization.dumps())
    assert ast_dict == {
        "_type": "Module",
        "body": [
            {
                "_type": "If",
                "body": [
                    {
                        "_type": "Assign",
                        "targets": [{"_type": "Name", "id": "b"}],
                        "value": {"_type": "Constant", "value": 1},
                    }
                ],
                "orelse": [
                    {
                        "_type": "Assign",
                        "targets": [{"_type": "Name", "id": "b"}],
                        "value": {"_type": "Constant", "value": "test"},
                    }
                ],
                "test": {
                    "_type": "Compare",
                    "comparators": [{"_type": "Constant", "value": 1}],
                    "left": {"_type": "Name", "id": "a"},
                    "ops": [{"_type": "Eq"}],
                },
            }
        ],
        "type_ignores": [],
    }

    src_code = ast_serialization.unparse(ast_dict)
    # print(src_code)
    assert src_code == source

    # manipulate ast_dict: set b = 2
    ast_dict["body"][0]["body"][0]["value"]["value"] = 2
    src_code = ast_serialization.unparse(ast_dict)
    # print(src_code)
    assert (
        src_code
        == """if a == 1:
    b = 2
else:
    b = 'test'"""
    )


def test_rdf_generation():
    ast_serialization = AstSerialization()
    source = """if a == 1:
    b = 1
else:
    b = 'test'"""

    ast_serialization.parse(source)
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

    expected_possible_values = [1, "test"]
    possible_values = [row[0].toPython() for row in qres]
    print(possible_values)
    assert possible_values == expected_possible_values


if __name__ == "__main__":
    test_ast_generation()
    test_rdf_generation()
