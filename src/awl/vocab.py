"""Language-neutral node vocabulary, orderings, profiles and noise lists.

Pure data. Modelled on Joern's Code Property Graph so a second language
frontend needs a new mapping, not a new vocabulary.
"""

from __future__ import annotations

from types import MappingProxyType

__all__ = [
    "AMBIENT_ANNOTATIONS",
    "AMBIENT_CALLEES",
    "FOLDS_KEYWORDS",
    "NODE_TYPES",
    "OPAQUE",
    "ORDERED_FIELDS",
    "PROFILES",
    "TRANSPARENT",
    "node_type_for",
    "operator_name_for",
]

NODE_TYPES = frozenset({
    "Method",
    "Block",
    "Call",
    "ControlStructure",
    "Identifier",
    "Literal",
    "Local",
    "Return",
    "TypeDecl",
    "Type",
    "Member",
    "Unknown",
})

_BY_NODE = MappingProxyType({
    "FunctionDef": "Method",
    "AsyncFunctionDef": "Method",
    "Lambda": "Method",
    "Module": "Block",
    "Interactive": "Block",
    "Expression": "Block",
    "Call": "Call",
    "If": "ControlStructure",
    "While": "ControlStructure",
    "For": "ControlStructure",
    "AsyncFor": "ControlStructure",
    "With": "ControlStructure",
    "AsyncWith": "ControlStructure",
    "Try": "ControlStructure",
    "TryStar": "ControlStructure",
    "Match": "ControlStructure",
    "Break": "ControlStructure",
    "Continue": "ControlStructure",
    "Name": "Identifier",
    "Constant": "Literal",
    "JoinedStr": "Literal",
    "FormattedValue": "Literal",
    "Return": "Return",
    "Yield": "Return",
    "YieldFrom": "Return",
    "Await": "Return",
    "ClassDef": "TypeDecl",
    "AnnAssign": "Member",
    # Operators are calls; see operator_name_for.
    "Assign": "Call",
    "AugAssign": "Call",
    "BinOp": "Call",
    "BoolOp": "Call",
    "UnaryOp": "Call",
    "Compare": "Call",
    "Attribute": "Call",
    "Subscript": "Call",
})

_OPERATORS = MappingProxyType({
    "Assign": "<operator>.assignment",
    "AnnAssign": "<operator>.assignment",
    "AugAssign": "<operator>.assignmentPlus",
    "Add": "<operator>.addition",
    "Sub": "<operator>.subtraction",
    "Mult": "<operator>.multiplication",
    "Div": "<operator>.division",
    "Mod": "<operator>.modulo",
    "Pow": "<operator>.exponentiation",
    "Eq": "<operator>.equals",
    "NotEq": "<operator>.notEquals",
    "Lt": "<operator>.lessThan",
    "LtE": "<operator>.lessEqualsThan",
    "Gt": "<operator>.greaterThan",
    "GtE": "<operator>.greaterEqualsThan",
    "And": "<operator>.logicalAnd",
    "Or": "<operator>.logicalOr",
    "Not": "<operator>.logicalNot",
    "Attribute": "<operator>.fieldAccess",
    "Subscript": "<operator>.indexAccess",
})


def node_type_for(ast_node_name: str) -> str:
    """Return the neutral node type for a Python AST node type name.

    Parameters
    ----------
    ast_node_name : str
        For example ``"While"``.

    Returns
    -------
    str
        A member of :data:`NODE_TYPES`. ``"Unknown"`` when unmapped, which is a
        deliberate answer rather than an error: the frontend keeps the raw
        label in ``parserTypeName``, so nothing is lost.
    """
    return _BY_NODE.get(ast_node_name, "Unknown")


def operator_name_for(ast_node_name: str) -> str | None:
    """Return the reserved call name for an operator node.

    Parameters
    ----------
    ast_node_name : str
        For example ``"Add"``.

    Returns
    -------
    str or None
        ``None`` when the node is not an operator. Returning ``None`` rather
        than inventing a name keeps vocabulary decisions out of the walker.
    """
    return _OPERATORS.get(ast_node_name)


#: Statement lists whose order is semantic, so the elision stage materializes an index on them.
ORDERED_FIELDS = ("body", "orelse", "finalbody")

_WRAPPERS = frozenset({"Expr", "arguments", "alias"})

#: Types unwrapped into their parent, per profile.
#:
#: ``ast`` elides nothing structural. An earlier design made ``Expr`` and
#: ``keyword`` transparent everywhere, which turned named arguments into
#: positional ones and flattened statements onto one line.
TRANSPARENT = MappingProxyType({
    "ast": frozenset(),
    "workflow": _WRAPPERS,
    "provenance": _WRAPPERS,
    "signature": _WRAPPERS,
})

#: ``keyword`` is never transparent: folding preserves the argument name.
FOLDS_KEYWORDS = MappingProxyType({"ast": False, "workflow": True, "provenance": True, "signature": True})

_EXPRESSIONS = frozenset({"BinOp", "BoolOp", "UnaryOp", "Compare", "ListComp", "DictComp", "SetComp", "GeneratorExp"})

#: Types reduced to a single node keeping their source text, per profile.
OPAQUE = MappingProxyType({
    "ast": frozenset(),
    "workflow": _EXPRESSIONS,
    "provenance": _EXPRESSIONS,
    "signature": _EXPRESSIONS,
})

PROFILES = tuple(TRANSPARENT)

#: Callees shared by every workflow, so they distinguish nothing.
#:
#: Deliberately small. Grow from evidence on the real corpus file rather than
#: from Graphify's lists, which encode what a repository is about.
AMBIENT_CALLEES = frozenset({
    "print",
    "len",
    "range",
    "enumerate",
    "zip",
    "isinstance",
    "getattr",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "tuple",
})

#: Annotations that carry no domain meaning.
AMBIENT_ANNOTATIONS = frozenset({
    "Optional",
    "Union",
    "List",
    "Dict",
    "Any",
    "Sequence",
    "Iterable",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "None",
})
