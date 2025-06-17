"""
ast_annotator_simple.py
-----------------------
Traverse a Python-AST-as-dict and collect a *flat* annotation that contains
only

* capitalised **constructors**  (Battery, Voltage, …)
* `battery.charge` / `battery.discharge` wrappers
  → unwrap the single constructor arg and add `"_function"`.

Everything else is ignored.

`debug=True`  strips the original AST, leaving only {"annotation": [...]}
"""

import json
from awl import AstSerialization


class ASTNotAModule(Exception):
    """Raised when the parsed object is not an AST Module."""


class AstAnnotation(AstSerialization):

    debug = True

    def __init__(self) -> None:
        super().__init__()
        # self.annotateAST()

    def parse(self,source):
        super().parse(source)
        self.annotate_ast()
        return self.ast_dict



    def annotate_ast(self) -> None:
        # check if self.ast_dict is Main dict of AST
        if self.ast_dict.get("_type") != "Module":
            raise ASTNotAModule("root node is not a Module")


        # iterative walk
        self._walk_json_ast(self.ast_dict, path=None)

        # # set the annotations
        self.ast_dict["annotation"] = "This is a comment"




    # ------------------------------------------------------------------ #
    # Recursive walk
    # ------------------------------------------------------------------ #

    def _walk_json_ast(self, node:list|dict|object, path: list) -> None:
        """
        Recursively walks the json AST, keeps the current path
        :param node:  The node object
        :param path:  The current path of the json AST node
        :return:
        """
        if path is None:
            path = []

        if isinstance(node, dict):
            for key, value in node.items():
                self._walk_json_ast(value, path + [key])

        elif isinstance(node, list):
            for index, item in enumerate(node):
                self._walk_json_ast(item, path + [index])
        #leaf level
        else:
            print(f"Path: {path} -> Value: {node}")
            pass

    def _get_from_path(self, node:list|dict|object, path:list) -> list|dict|object:
        """
        Retruns the node with the path
        :param node: original node
        :param path: path to target node
        :return: node of target path
        """
        for key in path:
            node = node[key]

        return node

    def _dump_from_path(self, node:list|dict|object, path:list) -> list|dict|object:
        node = self._get_from_path(node,path)
        res = json.dumps(node, indent=4)
        return res

if __name__ == "__main__":
    demo_src = (
        "battery = Battery(nominal_capacity=Capacity(value=4, unit=U.ampere_hour),min_operating_voltage=Voltage(value=4, unit=U.V))"
    )

    # demo_src = (
    #     "battery = Battery(nominal_capacity=Capacity(value=4, unit=U.ampere_hour),min_operating_voltage=Voltage(value=4, unit=U.V))\n"
    #     "while(i<3):\n"
    #     "   battery.discharge(ChargeParam(target_voltage=Voltage(value=4, unit=U.V),current=Current(value=2, unit=U.A)))\n"
    #     "   battery.charge(ChargeParam(target_voltage=Voltage(value=4, unit=U.V),current=Current(value=2, unit=U.A)))\n"
    #     "   i+=1"
    # )


    test = AstAnnotation()
    test.parse(demo_src)

    a = ['body', 0, 'value', 'keywords', 1, 'value']
    # a = []
    print(test._dump_from_path(test.ast_dict,a))

    # print(dbg.dumps(format="json"))
