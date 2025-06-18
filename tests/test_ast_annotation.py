# from awl import AstSerialization
# import json

from awl import AstAnnotation


def test_ast_annotation():
    # ------------------------------------------------------------------ #
    # Check that annotation doesnt effect unparsing
    # ------------------------------------------------------------------ #
    ast_annotation = AstAnnotation(parsable = True)

    source = ("""while i < 3:
    a = ClassA(a=1, b='b', c=ClassB(d=False))
    if a.a < 5:
        a.a += 1
    ClassB(a=1, b='b', c=ClassB(d=False))
    i += 1""")
    # print(source)

    ast_dict = ast_annotation.parse(source)
    # print(json.dumps(ast_dict, indent=4))
    src_code = ast_annotation.unparse(ast_dict)
    assert src_code == source


    ast_annotation = AstAnnotation(parsable = False)
    source = """ClassA(a=1, b='b', c=ClassB(d=False), e=A.B)"""
    ast_dict = ast_annotation.parse(source)
    ast_dumps = ast_annotation.dumps("json")
    print(ast_dumps)
    assert ast_dumps == """{
    "_type": "Module",
    "body": [
        {
            "_type": "Expr",
            "value": {
                "__class_name__": "ClassA",
                "a": 1,
                "b": "b",
                "c": {
                    "__class_name__": "ClassB",
                    "d": false
                },
                "e": "A.B"
            }
        }
    ],
    "type_ignores": []
}"""




if __name__ == "__main__":
    test_ast_annotation()
