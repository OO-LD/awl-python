# from awl import AstSerialization
from awl import AstAnnotation
import json

def test_ast_annotation():
    # ------------------------------------------------------------------ #
    # Check that annotation doesnt effect unparsing
    # ------------------------------------------------------------------ #

    ast_annotation = AstAnnotation()
    source = """if a == 1:
    b = 1
else:
    b = 'test'"""

    ast_dict = ast_annotation.parse(source)
    # print(json.dumps(ast_dict, indent=4))
    src_code = ast_annotation.unparse(ast_dict)
    assert src_code == source


if __name__ == "__main__":
    test_ast_annotation()

