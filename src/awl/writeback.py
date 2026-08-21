"""Apply editor changes back to source without disturbing untouched text.

Two tiers. A value edit patches the original text by source span and is
byte-exact everywhere else. A structural edit goes through ``libcst``, which
attaches comments and whitespace to named slots so trivia travels with the node
it belongs to.

Regenerating the file from the AST is not an option for the retrofit path.
``ast.parse`` has no comment node at all, so ``ast.unparse`` discards every
comment and reflows the layout. For workflows authored in the editor that is
irrelevant; for editing a laboratory's existing procedure files it is fatal,
and those are exactly the files this path targets.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from itertools import pairwise
from typing import Any

__all__ = ["apply_edits", "insert_statement", "span_of"]


def span_of(source: str, predicate: Callable[[ast.AST], bool]) -> tuple[int, int]:
    """Return the character span of the first AST node satisfying *predicate*.

    Parameters
    ----------
    source : str
        The original text.
    predicate : callable
        Receives an :class:`ast.AST` node, returns bool.

    Returns
    -------
    tuple of int
        ``(start, end)`` character offsets into *source*.

    Raises
    ------
    LookupError
        If no node matches, so a silent no-op edit is impossible.

    Notes
    -----
    A ``keyword`` node spans the whole ``name=value`` pair, so an editor
    patching a *value* must target the inner node or it overwrites the
    parameter name too.
    """
    import asttokens

    atok = asttokens.ASTTokens(source, parse=True)
    for node in ast.walk(atok.tree):
        if predicate(node):
            return atok.get_text_range(node)
    raise LookupError("no node matched the predicate")


def apply_edits(source: str, edits: list[dict[str, Any]]) -> str:
    """Apply non-overlapping span edits to *source*.

    Parameters
    ----------
    source : str
        Original text.
    edits : list of dict
        Each has ``start``, ``end`` and ``text``.

    Returns
    -------
    str
        The patched source. Every character outside an edited span is
        identical to the input: this is not a formatter and must not reflow,
        reindent or normalise quotes.

    Raises
    ------
    ValueError
        If two edits overlap, which would make the result order-dependent.

    Notes
    -----
    Edits are applied right to left so earlier offsets stay valid.
    """
    ordered = sorted(edits, key=lambda edit: edit["start"])
    for earlier, later in pairwise(ordered):
        if earlier["end"] > later["start"]:
            raise ValueError(f"overlapping edits: {earlier} and {later}")
    out = source
    for edit in reversed(ordered):
        out = out[: edit["start"]] + edit["text"] + out[edit["end"] :]
    return out


def insert_statement(
    source: str,
    *,
    into: str,
    code: str,
    leading_comment: str | None = None,
) -> str:
    """Append a statement to a control-structure body, preserving trivia.

    Parameters
    ----------
    source : str
        Original text.
    into : str
        The control structure to insert into. Only ``"while"`` is implemented.
    code : str
        The statement's expression source, e.g. ``"rest(600)"``.
    leading_comment : str or None, optional
        A comment line emitted above the new statement, including its ``#``.

    Returns
    -------
    str
        The patched source, with every pre-existing comment intact.

    Raises
    ------
    NotImplementedError
        If *into* names a structure with no insertion rule, rather than
        silently returning the source unchanged.

    Notes
    -----
    Span splicing cannot do this: it has no opinion about which comment
    belongs to which statement, so a moved node cannot carry its own. libcst
    attaches trivia to named slots and can.
    """
    if into != "while":
        raise NotImplementedError(f"insertion into {into!r} is not implemented")

    import libcst as cst

    leading = [cst.EmptyLine(comment=cst.Comment(leading_comment))] if leading_comment else []
    statement = cst.SimpleStatementLine(body=[cst.Expr(cst.parse_expression(code))], leading_lines=leading)

    class _Insert(cst.CSTTransformer):
        def leave_While(self, original_node, updated_node):
            return updated_node.with_changes(
                body=updated_node.body.with_changes(body=[*updated_node.body.body, statement])
            )

    return cst.parse_module(source).visit(_Insert()).code
