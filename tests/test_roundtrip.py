"""The round-trip guarantee, measured against code nobody wrote for this project.

The eight-file corpus is shaped to exercise particular features and is far too
small to establish that *any* syntax tree survives. Every defect below was
invisible to it and obvious here:

- seven of the grammar's twenty-nine sequence fields were missing from a
  hand-written list, so a dict literal's ``keys`` rebuilt as ``None``;
- ``ExceptHandler`` has a field named ``type``, which collided with the node
  type key and destroyed every ``try``/``except``;
- ``f(a=1, **rest)`` lost ``**rest``, and ``f(**rest, a=1)`` reordered it;
- ``u''`` lost its prefix;
- ``b'ab'``, ``...`` and ``1j`` all arrived as plain strings.
"""

import ast
import json
import os
import pathlib
import sysconfig

import pytest

from awl.astdoc import from_doc, to_doc
from awl.compact import decode, encode
from awl.elide import elide, unfold


def _library_files():
    """Return the standard library's modules, which no one wrote for us."""
    stdlib = pathlib.Path(sysconfig.get_paths()["stdlib"])
    return sorted(path for path in stdlib.rglob("*.py") if "lib2to3" not in path.parts)


#: Every module the interpreter ships. The full sweep takes minutes, so the
#: default run takes a deterministic slice of it and the whole set runs when
#: AWL_FULL_SWEEP is set. The slice is every seventh file rather than the
#: first N, so it spans the library instead of its alphabetical head.
_ALL = _library_files()
LIBRARY = _ALL if os.environ.get("AWL_FULL_SWEEP") else _ALL[::7]


def _parsed(paths):
    for path in paths:
        try:
            yield path, ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue


@pytest.mark.parametrize(
    "stage",
    [
        pytest.param(lambda tree: from_doc(to_doc(tree)), id="astdoc"),
        pytest.param(lambda tree: from_doc(unfold(elide(to_doc(tree), profile="ast"))), id="elide"),
        pytest.param(lambda tree: decode(encode(elide(to_doc(tree), profile="ast"))), id="compact"),
    ],
)
def test_every_library_module_regenerates(stage):
    """Total, not merely usual.

    Asserted at each stage of the faithful path, so a regression anywhere in
    it fails here. Set AWL_FULL_SWEEP to run against every module rather than
    the default slice; the full set was 1040 of 1040 when this was written.
    """
    failures = []
    checked = 0
    for path, tree in _parsed(LIBRARY):
        checked += 1
        try:
            restored = ast.unparse(ast.fix_missing_locations(stage(tree)))
        except Exception as exc:
            failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        if restored != ast.unparse(tree):
            failures.append(f"{path.name}: differs")
    assert checked > 100, f"only {checked} modules were parsed; the sweep is not running"
    assert not failures, f"{len(failures)} of {checked} failed, e.g. {failures[:3]}"


@pytest.mark.parametrize(
    "source",
    [
        "x = b'ab'",
        "x = ...",
        "x = 1j",
        "x = u''",
        "f(a=1, **rest)",
        "f(**rest, a=1)",
        "d = {'a': 1}",
        "y = [i for i in xs if i]",
        "try:\n    a()\nexcept ValueError as e:\n    b()",
        "match x:\n    case {'a': 1}:\n        pass",
        "async def f():\n    async with a() as b:\n        await c()",
    ],
    ids=[
        "bytes",
        "ellipsis",
        "complex",
        "u-string",
        "kwargs after named",
        "kwargs before named",
        "dict keys",
        "comprehension ifs",
        "except handler",
        "match mapping",
        "async",
    ],
)
def test_each_construct_that_was_measured_broken(source):
    """One case per defect the sweep found, so a regression names itself."""
    tree = ast.parse(source)
    restored = decode(encode(elide(to_doc(tree), profile="ast")))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


def test_no_ast_field_is_named_like_a_reserved_shorthand_key():
    """A tripwire for the collision that broke every try/except.

    `literal` and `var` are plain words and are safe only while no field is
    named that. `@type` cannot collide at all, because `@` is not valid in an
    identifier; these two rely on the grammar not moving under them.
    """
    fields = set()
    for name in dir(ast):
        cls = getattr(ast, name)
        if isinstance(cls, type) and issubclass(cls, ast.AST):
            fields |= set(getattr(cls, "_fields", ()))
    assert not fields & {"literal", "var", "span"}
    assert "type" in fields, "the collision that motivated @type is still real"


@pytest.mark.parametrize(
    "source",
    [
        "def f(a): pass",
        "def f(a: int = 1) -> None: pass",
        "def f(a, b=1, /, c=2, *rest, d, e=3, **kw): pass",
        "g = lambda x, *a, **k: x",
        "async def f(a: int): pass",
    ],
    ids=["plain", "annotated", "every slot", "lambda", "async"],
)
def test_a_signature_survives_losing_its_wrapper(source):
    """`arguments` groups a signature's seven slots and says nothing else.

    Which node type sits at `FunctionDef.args` is fixed by the grammar, so the
    wrapper is derivable and splicing it away is reversible. Every slot is
    covered here because the wrapper is the only thing that kept them apart.
    """
    tree = ast.parse(source)
    restored = decode(encode(elide(to_doc(tree), profile="ast")))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


def test_a_parameter_with_only_a_name_is_that_name():
    """Everything in a signature slot is an `arg`, so the label says nothing."""
    doc = encode(elide(to_doc(ast.parse("def f(a, *rest, **kw): pass")), profile="ast"))
    function = doc["body"][0]
    assert function["args"] == ["a"]
    assert function["vararg"] == "rest"
    assert function["kwarg"] == "kw"
    assert "arguments" not in json.dumps(doc)


def test_an_annotated_parameter_keeps_its_annotation():
    doc = encode(elide(to_doc(ast.parse("def f(cycles: int): pass")), profile="ast"))
    assert doc["body"][0]["args"] == [{"arg": "cycles", "annotation": {"var": "int"}}]
