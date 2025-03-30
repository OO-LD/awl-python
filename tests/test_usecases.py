import rdflib

from awl.core import AstSerialization


def test_tbox_generation():
    src_code = """
def MyProcess(input: MyInput) -> MyOutput:
  pass
"""
    ast_serialization = AstSerialization()
    ast_serialization.parse(src_code)
    print(ast_serialization.dumps())

    # add to graph
    g = rdflib.Graph()
    g.parse(data=ast_serialization.to_jsonld(), format="json-ld")
    print(g.serialize(format="turtle"))

    # query all awl:FunctionDef
    # construct owl restrictions for each arg type annotation
    # construct owl restrictions for return type annotation
    query = """
    PREFIX awl: <https://w3id.org/awl/schema/>
    PREFIX ex: <https://example.org/>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    CONSTRUCT {
        ?arg_type a owl:Class .
        ?return_type a owl:Class .
        ?f a owl:Class ;
            owl:equivalentClass [
                a owl:Restriction ;
                owl:onProperty awl:HasInput ;
                owl:someValuesFrom ?arg_type ;
            ] ;
            owl:equivalentClass [
                a owl:Restriction ;
                owl:onProperty awl:HasOutput ;
                owl:someValuesFrom ?return_type ;
            ] .
    }
    WHERE {
        ?f a awl:FunctionDef ;
            awl:HasArgumentList/awl:HasPart/awl:HasType ?arg_type ;
            awl:HasReturnType ?return_type .
    }
    """

    # print result as ttl
    qres = g.query(query)
    # import as a graph
    g = rdflib.Graph()
    g.parse(data=qres.serialize(format="json-ld"), format="json-ld")

    # add a dummy owl ontology
    g.parse(
        data="""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <https://example.org/> .
    @prefix awl: <https://w3id.org/awl/schema/> .
    ex:MyProcessInventory a owl:Ontology .
    """,
        format="ttl",
    )

    print(g.serialize(format="turtle"))


if __name__ == "__main__":
    test_tbox_generation()
