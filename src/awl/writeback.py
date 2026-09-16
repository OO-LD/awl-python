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
import contextlib
import io
import token as token_module
import tokenize
from collections.abc import Callable
from itertools import pairwise
from typing import Any

__all__ = ["apply_edits", "comment_text", "comments", "insert_statement", "offsets", "span_of", "trivia"]


def offsets(source: str, span: list[int]) -> dict[str, int]:
    """Return the character offsets of a document span.

    Parameters
    ----------
    source : str
        The original text.
    span : list of int
        ``[start_line, start_col, end_line, end_col]``, one-based lines and
        zero-based columns, as a document carries them.

    Returns
    -------
    dict
        ``start`` and ``end`` character offsets, which is what a patch needs.

    Notes
    -----
    Two coordinate systems meet here and neither can be dropped. A document
    locates a node by line and column, because that is what a parser reports
    and what survives an edit elsewhere in the file. A patch has to name
    character offsets, because that is the only way to replace a range without
    reflowing anything around it. Columns are byte-free: Python reports
    ``col_offset`` in UTF-8 bytes on some paths and in characters here, and
    this uses the character reading the document was built with.
    """
    start_line, start_col, end_line, end_col = span
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return {
        "start": starts[start_line - 1] + start_col,
        "end": starts[end_line - 1] + end_col,
    }


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

    # Parsed here rather than via parse=True so the tree is known to exist:
    # ASTTokens.tree is Optional, and a None slipping into ast.walk would fail
    # far from the cause.
    tree = ast.parse(source)
    atok = asttokens.ASTTokens(source, tree=tree)
    for node in ast.walk(tree):
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


def comments(source: str) -> dict[int, tuple[int, int, str]]:
    """Return every comment in *source*, by the line it is on.

    Parameters
    ----------
    source : str
        The module's text.

    Returns
    -------
    dict
        Line number to ``(start_col, end_col, text)``, the text without its
        ``#`` and the columns covering the comment token itself.

    Notes
    -----
    The tokenizer rather than a regular expression, because a ``#`` inside a
    string is not a comment and telling the two apart is what a tokenizer is
    for. Half-written source tokenizes as far as it gets and the rest is
    dropped, which is the same bargain an editor's source pane makes: a file
    that does not parse changes nothing.
    """
    found: dict[int, tuple[int, int, str]] = {}
    tokens: list[tokenize.TokenInfo] = []
    with contextlib.suppress(tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        tokens.extend(tokenize.generate_tokens(io.StringIO(source).readline))
    for entry in tokens:
        if entry.type == token_module.COMMENT:
            found[entry.start[0]] = (entry.start[1], entry.end[1], entry.string.lstrip("#").strip())
    return found


def trivia(source: str, span: list[int] | None) -> dict[str, Any]:
    """Return the comment the statement at *span* carries, and the range an edit rewrites.

    Parameters
    ----------
    source : str
        The module's text.
    span : list or None
        ``[start_line, start_col, end_line, end_col]``.

    Returns
    -------
    dict
        ``text``, the comment without its ``#``; ``span``, the range to rewrite,
        zero width where there is no comment yet and one would be written; and
        ``where``, ``beside``, ``above`` or ``""``.

    Notes
    -----
    Here rather than in an editor, because the syntax tree has no comment node
    and every canvas that wants one would otherwise tokenize the source itself.
    The write half needs nothing new: the range this returns goes to
    :func:`apply_edits` like any other span patch, so a note survives being
    edited and the rest of the file does not move.

    Two places, and only two. A comment **beside** the statement, on the line it
    starts on, is unambiguously about it. One **above** it, on the line before at
    the statement's own indentation, usually is.

    Only the line immediately above, never a run of them. Nothing here can tell
    a banner from commented-out code, and claiming a four line block as one
    statement's explanation would put dead code into an input that writes it
    back as prose. A run keeps its lines as trivia and the nearest one is the
    note, which is a rule rather than an answer: there is no answer without a
    concrete-syntax tree.
    """
    if not span:
        return {"text": "", "span": [], "where": ""}
    line, column = span[0], span[1]
    lines = source.splitlines()
    marks = comments(source)

    beside = marks.get(line)
    if beside is not None and beside[0] > column:
        # From the end of the code to the end of the comment, so removing a note
        # takes the run of spaces before it rather than leaving a ragged tail.
        code = len(lines[line - 1][: beside[0]].rstrip()) if line <= len(lines) else beside[0]
        return {"text": beside[2], "span": [line, code, line, beside[1]], "where": "beside"}

    above = marks.get(line - 1)
    if above is not None and above[0] == column and _only_comment(lines, line - 1):
        # The whole line, newline included, so an emptied note leaves no blank
        # line where the comment was.
        return {"text": above[2], "span": [line - 1, 0, line, 0], "where": "above"}

    # At the end of the statement, which is not always the end of its first
    # line. A statement whose first line ends inside a multi-line string put the
    # note *inside the literal*: writing one on a docstring produced
    # ``\"\"\"  # NOTE`` and silently changed what the string said, while
    # reporting success and leaving `reformats()` false.
    at = _closing_line(source, span)
    tail = len(lines[at - 1].rstrip()) if at <= len(lines) else column
    return {"text": "", "span": [at, tail, at, tail], "where": ""}


def _closing_line(source: str, span: list[int]) -> int:
    """Return the line a note may be appended to for the statement at *span*.

    The statement's first line, unless a token starting on or before it runs
    past it, in which case the line that token ends on. A compound statement is
    unaffected: its header line ends at the colon and nothing spans it.
    """
    line = span[0]
    tokens: list[tokenize.TokenInfo] = []
    with contextlib.suppress(tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        tokens.extend(tokenize.generate_tokens(io.StringIO(source).readline))
    for entry in tokens:
        if entry.start[0] <= line < entry.end[0] and entry.end[0] <= span[2]:
            line = entry.end[0]
    return line


def _only_comment(lines: list[str], line: int) -> bool:
    """Return whether a line holds nothing but a comment."""
    return 1 <= line <= len(lines) and lines[line - 1].lstrip().startswith("#")


def comment_text(note: str, where: str, indent: int) -> str:
    """Return what a note edit writes into the range :func:`trivia` reported.

    Parameters
    ----------
    note : str
        What the reader typed, with or without a ``#``.
    where : str
        ``above`` for a comment on a line of its own; anything else writes it
        beside the statement, which is where a first note goes.
    indent : int
        The statement's own column, for a note written on a line of its own.

    Returns
    -------
    str
        The replacement text, empty when the note was cleared.
    """
    # One line, because a comment is one line. A note carrying a newline was
    # written through verbatim, so "note\nimport os" added an import to the
    # file and the reparse accepted it.
    body = " ".join(note.strip().lstrip("#").split())
    if not body:
        return ""
    if where == "above":
        return f"{' ' * indent}# {body}\n"
    return f"  # {body}"
