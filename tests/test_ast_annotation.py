# from awl import AstSerialization
# import json
import pytest

from awl import ASTNotAModule, AstSerialization


def test_ast_annotation():
    # ------------------------------------------------------------------ #
    # Check that trying to annotate something that is not
    # ------------------------------------------------------------------ #
    ast_annotation = AstSerialization(annotate=True, backparsable=True)
    ast_annotation.ast_dict = {}
    with pytest.raises(ASTNotAModule):
        ast_annotation.annotate_ast()

    # ------------------------------------------------------------------ #
    # Check that annotation doesnt effect unparsing
    # ------------------------------------------------------------------ #
    ast_annotation = AstSerialization(annotate=True, backparsable=True)

    source = """while i < 3:
    a = ClassA(a=1, b='b', c=ClassB(d=False))
    if a.a < 5:
        a.a += 1
    ClassB(a=1, b='b', c=ClassB(d=False))
    i += 1"""
    # print(source)

    ast_dict = ast_annotation.parse(source)
    # print(json.dumps(ast_dict, indent=4))
    src_code = ast_annotation.unparse(ast_dict)
    assert src_code == source
    # ------------------------------------------------------------------ #
    # Check the annotation
    # ------------------------------------------------------------------ #
    ast_annotation = AstSerialization(annotate=True, backparsable=False)
    source = """ClassA(a=1, b='b', c=ClassB(d=False), d=t, e=A.B)"""
    ast_dict = ast_annotation.parse(source)
    ast_dumps = ast_annotation.dumps("json")
    print(ast_dumps)
    assert (
        ast_dumps
        == """{
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
                "d": "t",
                "e": "A.B"
            }
        }
    ],
    "type_ignores": []
}"""
    )

    example_path = ["body", 0, "value", "__class_name__"]
    print(ast_annotation._dump_from_path(ast_annotation.ast_dict, example_path))
    assert (
        ast_annotation._dump_from_path(ast_annotation.ast_dict, example_path)
        == '"ClassA"'
    )


if __name__ == "__main__":
    test_ast_annotation()
