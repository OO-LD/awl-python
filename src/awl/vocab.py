"""Language-neutral node vocabulary, orderings, profiles and noise lists.

Pure data. Modelled on Joern's Code Property Graph so a second language
frontend needs a new mapping, not a new vocabulary.
"""

from __future__ import annotations

from types import MappingProxyType

__all__ = [
    "AMBIENT_ANNOTATIONS",
    "AMBIENT_CALLEES",
    "EMBEDS_CONTEXT",
    "FOLDS_KEYWORDS",
    "LAYERS",
    "LOOKUPS",
    "MATERIALIZES_ORDERINGS",
    "MATERIALIZES_SPANS",
    "NODE_TYPES",
    "OPAQUE",
    "ORDERED_FIELDS",
    "PROFILES",
    "TRANSPARENT",
    "node_type_for",
    "operator_name_for",
    "round_trips",
    "statement_types",
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
        label in ``parser_type_name``, so nothing is lost.
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


def statement_types() -> frozenset[str]:
    """Return the names of every statement node type.

    Used to decide whether an item in a body needs an ``Expr`` wrapper put
    back. Derived from the ``ast`` module rather than listed, so a new
    statement type in a future Python needs no edit here.
    """
    import ast as _ast

    return frozenset(
        name
        for name in dir(_ast)
        if isinstance(getattr(_ast, name), type) and issubclass(getattr(_ast, name), _ast.stmt)
    )


#: Statement-position wrappers that are reversible, so every profile drops
#: them. An ``Expr`` exists only because Python needs a statement to hold an
#: expression; which items in a body need one is derivable, so re-wrapping on
#: the way out loses nothing.
#:
#: ``keyword`` is deliberately absent: splicing a keyword out discards its
#: name, which is a semantic change and not a wrapper removal. It folds
#: instead.
_REVERSIBLE_WRAPPERS = frozenset({"Expr"})

#: Types unwrapped into their parent, per profile.
TRANSPARENT = MappingProxyType({
    "ast": _REVERSIBLE_WRAPPERS,
    "workflow": _WRAPPERS,
    "provenance": _WRAPPERS,
    "signature": _WRAPPERS,
})

#: ``keyword`` is never transparent: folding preserves the argument name,
#: where splicing the value out discards it.
#:
#: Every profile folds, including the faithful one, because folding is a
#: reversible rewrite rather than a loss: ``awl.collapse.expand`` restores the
#: keyword list. Leaving it off for ``ast`` bought nothing and prevented the
#: constructor collapse from ever firing on the profile that regenerates code,
#: which is the one place it is most useful.
FOLDS_KEYWORDS = MappingProxyType({"ast": True, "workflow": True, "provenance": True, "signature": True})

_EXPRESSIONS = frozenset({"BinOp", "BoolOp", "UnaryOp", "Compare", "ListComp", "DictComp", "SetComp", "GeneratorExp"})

#: Types reduced to a single node keeping their source text, per profile.
OPAQUE = MappingProxyType({
    "ast": frozenset(),
    "workflow": _EXPRESSIONS,
    "provenance": _EXPRESSIONS,
    "signature": _EXPRESSIONS,
})

PROFILES = tuple(TRANSPARENT)

#: What a document can hold beyond the tree. The tree says what was written;
#: each of the others is a lookup over it, answering a question the tree alone
#: cannot: how control moves, what a name refers to, which typed member a value
#: was written to, and where a value came from.
LAYERS = ("document", "plan", "names", "writes", "definitions")

#: The lookups each profile runs, alongside TRANSPARENT, OPAQUE and
#: FOLDS_KEYWORDS: a profile is a named set of generator parameters, not a
#: separate code path. Every profile looks up everything today, because the
#: reduced ones are paused; they differ here first when they are defined, since
#: a lookup is what a profile's question needs rather than what its tree shows.
LOOKUPS = MappingProxyType(dict.fromkeys(TRANSPARENT, LAYERS))

#: Whether a profile's document carries the orderings that array position
#: already implies.
#:
#: The editor model leaves them out, because an editor that reorders a body
#: would leave the numbers stale. A document that is going to be projected must
#: carry them: ``@container: @list`` yields an RDF collection, a collection
#: yields members rather than positions, and SPARQL 1.1 property paths have
#: only ``*``, ``+`` and ``?``, so nothing downstream can count the hops back.
MATERIALIZES_ORDERINGS = MappingProxyType(dict.fromkeys(TRANSPARENT, True))

#: Whether a profile's document locates every node of the tree.
#:
#: On, because a span is what joins the tree to everything looked up beside it.
#: The tree's nodes are anonymous and the plan, the names and the def-use graph
#: are minted identities, so with no span in common they sit in one graph and
#: touch nowhere: "which call does the loop body run" has no answer. It is also
#: the join key for patching a file in place and for a trace overlay.
#:
#: The editor model is the exception and asks for it explicitly, because
#: regenerating code does not need it and carrying it doubles the tree.
MATERIALIZES_SPANS = MappingProxyType(dict.fromkeys(TRANSPARENT, True))

#: Whether a collapsed node carries its own ``@context``.
#:
#: Off: the document context already scopes every class's terms under the class
#: term, so embedding the same map per node repeats it once per constructor
#: call. It is worth turning on for a node travelling on its own, away from the
#: document that would interpret it.
EMBEDS_CONTEXT = MappingProxyType(dict.fromkeys(TRANSPARENT, False))


def round_trips(profile: str) -> bool:
    """Return whether a profile's documents can be read back.

    Derived from the parameters rather than listed beside them. A profile that
    unwraps only reversible wrappers and makes nothing opaque has dropped
    nothing, so it can be reconstructed; any other has, and no importer can
    recover what is gone. Listing the round-trippable profiles by hand meant a
    profile added to the tables above was treated as round-trippable by
    default, which is the wrong way for that mistake to fall.
    """
    return TRANSPARENT[profile] <= _REVERSIBLE_WRAPPERS and not OPAQUE[profile]


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
