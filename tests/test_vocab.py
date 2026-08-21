"""The language-neutral vocabulary, orderings and profile sets.

Imports only the module under test.
"""

import ast

import pytest

from awl.vocab import (
    FOLDS_KEYWORDS,
    NODE_TYPES,
    OPAQUE,
    PROFILES,
    TRANSPARENT,
    node_type_for,
    operator_name_for,
)


def test_every_ast_node_type_maps_to_the_vocabulary():
    """No node may be silently unmapped. Unknown is a legitimate answer."""
    unmapped = [
        name
        for name in dir(ast)
        if isinstance(getattr(ast, name), type)
        and issubclass(getattr(ast, name), ast.AST)
        and node_type_for(name) not in NODE_TYPES
    ]
    assert not unmapped, f"unmapped: {unmapped}"


def test_an_unrecognised_node_is_Unknown_not_an_error():
    """The tripwire is explicit, because .get() cannot raise.

    A new Python version adding a node type surfaces as Unknown here, and the
    mapping table is then extended deliberately.
    """
    assert node_type_for("SomeFuturePython315Node") == "Unknown"


def test_the_vocabulary_is_closed():
    """Growth here is a design change, not an implementation detail."""
    assert len(NODE_TYPES) == 12


def test_control_flow_uses_one_type_with_a_discriminator():
    """Not one class per construct. Same reason Joern has no ASSIGNMENT node."""
    for name in ("If", "While", "For", "Try", "Match", "Break"):
        assert node_type_for(name) == "ControlStructure"


def test_no_vocabulary_name_is_python_specific():
    """A Java or TypeScript frontend must be able to use these names as-is."""
    assert not (NODE_TYPES & {"AugAssign", "Expr", "arguments", "keyword", "Constant", "Name"})


def test_operators_are_calls_with_reserved_names():
    assert node_type_for("BinOp") == "Call"
    assert operator_name_for("Add") == "<operator>.addition"
    assert operator_name_for("AugAssign") == "<operator>.assignmentPlus"
    assert operator_name_for("Call") is None


def test_the_ast_profile_elides_nothing_structural():
    """Guards the regression that turned named arguments into positional ones."""
    assert TRANSPARENT["ast"] == frozenset()
    assert OPAQUE["ast"] == frozenset()


def test_keyword_is_never_transparent():
    """Folding preserves the argument name; transparency destroyed it."""
    for profile in PROFILES:
        assert "keyword" not in TRANSPARENT[profile]


@pytest.mark.parametrize("profile", ["ast", "workflow", "provenance", "signature"])
def test_every_profile_folds_keywords(profile):
    """Folding reverses, so no profile has a reason to skip it.

    The faithful profile in particular: without folding, the constructor
    collapse could never fire on the one profile that regenerates code.
    """
    assert FOLDS_KEYWORDS[profile] is True


TYPESCRIPT_EQUIVALENTS = [
    ("function_declaration", "Method"),
    ("statement_block", "Block"),
    ("while_statement", "ControlStructure"),
    ("call_expression", "Call"),
    ("new_expression", "Call"),
    ("number", "Literal"),
    ("identifier", "Identifier"),
]


@pytest.mark.parametrize("ts_node,expected", TYPESCRIPT_EQUIVALENTS)
def test_the_vocabulary_has_a_home_for_typescript(ts_node, expected):
    """A second frontend must need a new mapping, not new node types.

    `call_expression` and `new_expression` are distinct in that grammar and the
    same thing semantically, which is the discriminator design earning its keep.
    """
    assert expected in NODE_TYPES
