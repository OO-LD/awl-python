"""Compact AST codec: the editor model for AWL-LD workflows.

Both ends speak ``AstDoc``, so this composes with the elision stage.

Three node forms, named rather than punctuated:

==========================  =========================================
``{"@type": "While", ...}``  a typed node, the same key a collapsed
                            constructor uses
``{"literal": 4.2}``        a constant
``{"var": "i"}``            a name reference
==========================  =========================================

The node type uses the JSON-LD keyword rather than a plain word, and that is
a correctness requirement rather than a style choice. A node carries its
fields as sibling keys, and AST field names are arbitrary identifiers:
``ExceptHandler`` has a field literally called ``type``. Spelling the node
type ``type`` silently destroyed every ``try``/``except`` in the standard
library. ``@`` cannot appear in a Python identifier, so the keyword namespace
is the only one a field can never occupy.

``literal`` and ``var`` stay plain words because they are complete nodes on
their own and never sit beside fields, so nothing can collide with them.

An earlier revision used ``_``, ``c`` and ``$``, chosen to save bytes before
the document was JSON-LD. They saved about four percent and cost a reader
having to learn a private punctuation scheme sitting next to ``type``, in a
document meant to be edited by hand. ``type`` in particular now means one
thing everywhere: an ``ast`` node type and a collapsed class name are both
"what this is".

``@value`` was the obvious JSON-LD choice for a literal and is unusable here:
a value object may carry only ``@value``, ``type``, ``@language``, ``@index``
and ``@direction``, so a literal could not also carry ``argument_index``.
"""

from __future__ import annotations

import ast
import json
from typing import Any

from awl.vocab import ORDERED_FIELDS

__all__ = ["decode", "dumps", "encode", "link_names", "link_trivia", "name_spans", "number_items"]

NEWLINE = chr(10)


def _list_fields() -> frozenset[str]:
    """Return every field the grammar declares as a sequence.

    Derived from the ``ast`` annotations rather than listed by hand. The hand
    list was missing seven of the twenty-nine, including ``keys`` on a dict
    literal and ``ifs`` on a comprehension, so those rebuilt as ``None`` and
    raised deep inside the unparser. A list that has to be maintained against
    a moving grammar will drift; this cannot.
    """
    found = set()
    for name in dir(ast):
        cls = getattr(ast, name)
        if not (isinstance(cls, type) and issubclass(cls, ast.AST)):
            continue
        for field, annotation in getattr(cls, "__annotations__", {}).items():
            if "list" in str(annotation):
                found.add(field)
    return frozenset(found)


_LIST_FIELDS = _list_fields()

# Derivable or positional; never carried.
_DROP = frozenset({
    "argument_index",
    "argument_name",
    "col_offset",
    "ctx",
    "end_col_offset",
    "end_lineno",
    "lineno",
    "n",
    "order",
    "s",
    "type_comment",
})

# Fields holding an operator node, which carries nothing but its own type, so
# it is written as a bare name. Derived from the grammar rather than guessed:
# these are the only two fields typed by operator, unaryop, boolop or cmpop.
_OPERATOR_FIELDS = frozenset({"op", "ops"})

# Nodes whose `args` field is an `arguments` wrapper. The wrapper exists only
# to group a signature's seven slots, and which node type sits there is fixed
# by the grammar, so it is spliced into the parent and rebuilt on the way out.
_SIGNATURE_HOLDERS = frozenset({"FunctionDef", "AsyncFunctionDef", "Lambda"})

# The slots a signature is made of.
_ARGUMENT_FIELDS = tuple(ast.arguments._fields)

# Fields whose element type is fixed by the grammar, so the label says
# nothing. Each maps to the node type it may only ever hold, and to the field
# that alone is enough to name it.
_IMPLIED_TYPES = {
    "args": ("arg", "arg"),
    "posonlyargs": ("arg", "arg"),
    "kwonlyargs": ("arg", "arg"),
    "vararg": ("arg", "arg"),
    "kwarg": ("arg", "arg"),
    "names": ("alias", "name"),
}
_ARG_FIELDS = frozenset({"args", "posonlyargs", "kwonlyargs", "vararg", "kwarg"})

# Orderings are derivable from array position here and are **not** carried.
# They are materialized in the RDF projection, where position is not
# recoverable: an rdf:List yields members, and SPARQL property paths cannot
# count. Carrying them in this document would duplicate what the array already
# says, and let an editor reorder the array while leaving the numbers stale.
_ORDERINGS = ("order", "argument_index", "argument_name")
_SHORTHAND_EXTRA = frozenset({"span"})


def number_items(doc: Any) -> Any:
    """Return *doc* with every ordered statement carrying its sibling slot.

    Parameters
    ----------
    doc : dict or list or scalar
        A ``CompactDoc``.

    Returns
    -------
    dict or list or scalar
        A new document.

    Notes
    -----
    The editor model leaves the number out, because the array already says it
    and an editor that reorders a body would leave it stale. A document that is
    going to be projected cannot: ``@container: @list`` yields an RDF
    collection, a collection yields members rather than positions, and SPARQL
    1.1 property paths have only ``*``, ``+`` and ``?``, so a query downstream
    cannot count the ``rdf:rest`` hops back. This integer is the query surface,
    added at the one point where position stops being recoverable.
    """
    if isinstance(doc, list):
        return [number_items(item) for item in doc]
    if not isinstance(doc, dict):
        return doc

    numbered = {key: number_items(value) for key, value in doc.items()}
    for field in ORDERED_FIELDS:
        sequence = numbered.get(field)
        if not isinstance(sequence, list):
            continue
        numbered[field] = [
            {**item, "order": position} if isinstance(item, dict) else item for position, item in enumerate(sequence)
        ]
    return numbered


def link_names(doc: Any, bindings: list[dict[str, Any]]) -> Any:
    """Return *doc* with each name reference pointing at what it refers to.

    Parameters
    ----------
    doc : dict or list or scalar
        A ``CompactDoc``.
    bindings : list of dict
        What :func:`awl.resolve.resolve` produced for the same module.

    Returns
    -------
    dict or list or scalar
        A new document. A ``var`` node gains ``refers_to`` when the name it
        holds could be resolved, and is left alone when it could not.

    Notes
    -----
    Joined by span where the document has one, because a name is scope-blind
    and two functions may both call something named ``run``. Where it has no
    span the join falls back to the name, and only when every use of that name
    in the module resolved to one identity: an ambiguous name is left
    unresolved rather than pointed at whichever binding was seen last.

    The editor model does not carry this. It regenerates source from the name
    as written, and what that name refers to is a judgement with a confidence
    behind it, which the ``names`` lookup records as such.
    """
    by_span: dict[tuple[Any, Any], str] = {}
    by_name: dict[str, set[str]] = {}
    for binding in bindings:
        identity = (binding.get("identity") or {}).get("iri")
        span = binding.get("span") or {}
        if not identity:
            continue
        if span:
            by_span[(span.get("start_line"), span.get("start_col"))] = identity
        by_name.setdefault(binding.get("local_name", ""), set()).add(identity)

    unambiguous = {name: next(iter(found)) for name, found in by_name.items() if len(found) == 1}
    return _link(doc, by_span, unambiguous)


def _link(doc: Any, by_span: dict[tuple[Any, Any], str], unambiguous: dict[str, str]) -> Any:
    """Walk *doc*, resolving each ``var`` node."""
    if isinstance(doc, list):
        return [_link(item, by_span, unambiguous) for item in doc]
    if not isinstance(doc, dict):
        return doc

    linked = {key: _link(value, by_span, unambiguous) for key, value in doc.items()}
    name = doc.get("var")
    if not isinstance(name, str):
        return linked

    span = doc.get("span")
    identity = by_span.get((span[0], span[1])) if isinstance(span, list) and len(span) == 4 else None
    identity = identity or unambiguous.get(name)
    if identity:
        linked["refers_to"] = {"@id": identity}
    return linked


def link_steps(doc: Any, steps: list[dict[str, Any]]) -> Any:
    """Return *doc* with each statement carrying the identity the plan minted for it.

    Parameters
    ----------
    doc : dict or list or scalar
        A ``CompactDoc``, with spans kept.
    steps : list of dict
        What :func:`awl.controlflow.analyze` produced for the same module.

    Returns
    -------
    dict or list or scalar
        A new document. A statement the plan recorded gains ``@id``; every
        other node is left anonymous.

    Notes
    -----
    The plan already mints an identity for each statement, from the same
    ``ast.stmt`` the tree is encoded from, and then throws it away on the tree's
    side. The two layers then described one statement as two nodes, joined only
    by carrying equal span coordinates, so a query that wanted the plan's
    successor and the tree's callee had to match four numbers to say "the same
    statement". That is matching by coincidence: it is the objection to joining
    on a name, one level down.

    With the identity on both, there is nothing to join. The tree's statement
    and the plan's step are the same subject, and the plan's ``next`` and
    ``when_true`` land on the node that carries the source.

    Matched here by span, but only within one parse of one file, where the
    coordinates come from the same tree that produced both sides. That is a
    build-time lookup, not something a reader of the document has to repeat.
    """
    by_span = {
        (span.get("start_line"), span.get("start_col"), span.get("end_line"), span.get("end_col")): step["id"]
        for step in steps
        for span in [step.get("span") or {}]
        if step.get("id") and span
    }
    return _identify(doc, by_span)


def _identify(doc: Any, by_span: dict[tuple[Any, ...], str]) -> Any:
    """Walk *doc*, stamping the identity of every statement that has one."""
    if isinstance(doc, list):
        return [_identify(item, by_span) for item in doc]
    if not isinstance(doc, dict):
        return doc

    identified = {key: _identify(value, by_span) for key, value in doc.items()}
    span = doc.get("span")
    if isinstance(span, list) and len(span) == 4:
        identity = by_span.get((span[0], span[1], span[2], span[3]))
        if identity:
            # First, so a reader meets the node's name before its contents, and
            # overriding rather than merged: `{"@id": x, **node}` let a node that
            # already carried an `@id` keep it, so the plan's identity was
            # silently dropped and the two layers stayed two nodes.
            return {"@id": identity, **{key: value for key, value in identified.items() if key != "@id"}}
    return identified


#: Slots holding a statement list. A comment stranded at the end of one belongs
#: to the slot rather than to any statement in it, so the key is named after it.
#:
#: Matched together with "is this a list", never by name alone. ``Lambda.body``,
#: ``IfExp.body`` and ``IfExp.orelse`` are *expression* slots wearing the same
#: names, and taking them for statement lists gave ``f = lambda: g()  # note``
#: its comment to the call inside the lambda and ``x = a if c else b  # note``
#: its comment to ``a``.
BLOCK_SLOTS = ("body", "orelse", "finalbody")


def link_trivia(doc: Any, source: str) -> Any:
    """Return *doc* with each statement carrying the comment written about it.

    Parameters
    ----------
    doc : dict or list or scalar
        A ``CompactDoc``, with spans kept.
    source : str
        The text the document was built from.

    Returns
    -------
    dict or list or scalar
        A new document. A statement gains ``comment``; a block whose last lines
        are comments gains ``<slot>_footer``; the module gains ``header`` and
        ``footer`` for what belongs to the file rather than to any statement.

    Notes
    -----
    The syntax tree has no comment node, so without this a comment exists only
    in the source and no projection of the document can see it. Derived from
    comment positions against the spans the document already carries, rather
    than from a second parse: a concrete-syntax library would say the same thing
    and would make the document layer depend on one.

    **One line, and only one.** A comment beside a statement is unambiguously
    about it. The single line directly above it, at its own indentation, usually
    is. A run above that is *not* claimed: nothing here can tell a banner from
    commented-out code, and claiming four lines as one statement's explanation
    would put dead code into a field that reads as prose.

    **Two places that are not statements**, both of which strand a comment
    otherwise: the end of a block, after its last statement, and the head and
    tail of the file. A comment at the end of a body would otherwise attach to
    whatever follows the block, which is outside it.
    """
    marks = dict(_comment_marks(source))
    lines = source.splitlines()
    stamped = _attach(doc, marks, lines, nearest=_nearest_on_line(doc))
    if not isinstance(stamped, dict):
        return stamped

    body = stamped.get("body")
    first = _first_span(body)
    last = _last_span(body)
    header = [_note(line, marks.pop(line)) for line in sorted(marks) if first is None or line < first[0]]
    footer = [_note(line, marks.pop(line)) for line in sorted(marks) if last is not None and line > last[2]]

    # The last header line, when it sits directly above the first statement with
    # no blank between, is that statement's note and not the file's. Leaving it
    # in the header shows a file with a comment over its first block and a block
    # with no comment, which reads as a defect rather than as a rule.
    first_note = body[0].get("comment") if body and isinstance(body[0], dict) else None
    directly_above = (
        header
        and first is not None
        and header[-1]["span"][0] == first[0] - 1
        # At the statement's own column, which is the rule `_note_for` applies
        # everywhere else. Without it an indented comment over a column-zero
        # statement became its note here and stayed invisible to
        # `writeback.trivia`, so the document showed a note the editor could
        # not see and writing one added a second.
        and header[-1]["span"][1] == first[1]
    )
    if directly_above and first_note is None and body:
        moved = header.pop()
        body[0]["comment"] = {"text": moved["text"], "where": "above", "span": moved["span"]}

    if header:
        stamped["header"] = header
    if footer:
        stamped["footer"] = footer
    return stamped


def _comment_marks(source: str) -> dict[int, tuple[int, int, str]]:
    """Return every comment by line, without importing the write-back module."""
    from awl import writeback

    return writeback.comments(source)


def _note(line: int, mark: tuple[int, int, str]) -> dict[str, Any]:
    """Return one comment as the document carries it."""
    return {"text": mark[2], "span": [line, mark[0], line, mark[1]]}


def _first_span(body: Any) -> list[int] | None:
    for item in body or []:
        if isinstance(item, dict) and isinstance(item.get("span"), list):
            return item["span"]
    return None


def _last_span(body: Any) -> list[int] | None:
    found = None
    for item in body or []:
        if isinstance(item, dict) and isinstance(item.get("span"), list):
            found = item["span"]
    return found


def _nearest_on_line(
    doc: Any, found: dict[int, tuple[int, int]] | None = None, statement: bool = False
) -> dict[int, tuple[int, int]]:
    """Return, per line, which statement a comment at the end of it is about.

    Reaching furthest right wins, because a line can hold more than one
    statement and a trailing comment is about the last of them:
    ``a = 1; b = 2  # both`` is a note on ``b``. Where two reach equally far the
    outermost wins, which is the one a canvas draws: in ``if x: g()  # both``
    the ``if`` and the call it holds both end at the same column, and the note
    belongs to the ``if``.

    Without this the walk order decided, so the note went to whichever
    statement was reached first and disagreed with :func:`awl.writeback.trivia`
    on the same source.
    """
    found = {} if found is None else found
    if isinstance(doc, list):
        for item in doc:
            _nearest_on_line(item, found, statement)
        return found
    if not isinstance(doc, dict):
        return found
    span = doc.get("span")
    if statement and isinstance(span, list) and len(span) == 4 and span[0] == span[2]:
        reach = (span[3], -span[1])
        found[span[0]] = max(found.get(span[0], (-1, -1)), reach)
    for key, value in doc.items():
        _nearest_on_line(value, found, key in BLOCK_SLOTS and isinstance(value, list))
    return found


def _attach(
    doc: Any,
    marks: dict[int, tuple[int, int, str]],
    lines: list[str],
    statement: bool = False,
    nearest: dict[int, tuple[int, int]] | None = None,
) -> Any:
    """Walk *doc*, consuming each comment onto the statement it belongs to.

    Only a statement takes one. Every node carries a span, so without this the
    innermost expression on the line won the comment: ``limit = cycles`` gave
    its note to ``cycles``, because the walk reaches the value before the
    assignment that holds it and a trailing comment is to the right of both.
    """
    if isinstance(doc, list):
        return [_attach(item, marks, lines, statement, nearest) for item in doc]
    if not isinstance(doc, dict):
        return doc

    out = {
        key: _attach(value, marks, lines, key in BLOCK_SLOTS and isinstance(value, list), nearest)
        for key, value in doc.items()
    }
    span = doc.get("span")
    if statement and isinstance(span, list) and len(span) == 4:
        found = _note_for(span, marks, lines, nearest or {})
        if found:
            out["comment"] = found
    for slot in BLOCK_SLOTS:
        if isinstance(out.get(slot), list) and isinstance(span, list) and len(span) == 4:
            stranded = _footer_for(out[slot], span, marks, lines)
            if stranded:
                out[f"{slot}_footer"] = stranded
    return out


def _note_for(
    span: list[int],
    marks: dict[int, tuple[int, int, str]],
    lines: list[str],
    nearest: dict[int, tuple[int, int]],
) -> dict[str, Any] | None:
    """Return the comment a statement carries, consuming it from *marks*."""
    line, column = span[0], span[1]

    beside = marks.get(line)
    closest = nearest.get(line)
    if beside is not None and beside[0] > column and (closest is None or (span[3], -column) == closest):
        return {**_note(line, marks.pop(line)), "where": "beside"}

    above = marks.get(line - 1)
    if above is not None and above[0] == column and _only_comment(lines, line - 1):
        return {**_note(line - 1, marks.pop(line - 1)), "where": "above"}
    return None


def _footer_for(
    block: Any, owner: list[int], marks: dict[int, tuple[int, int, str]], lines: list[str]
) -> list[dict[str, Any]]:
    """Return the comments stranded after a block's last statement.

    Bounded by indentation and not by the owner's span, because a span ends at
    the last *statement*: a comment on the line after it is outside the ``while``
    that encloses it, and would otherwise attach to whatever follows the block.

    Comment-only lines, and nothing else. The first statement after a loop
    usually sits at the loop's own indentation, and a comment written beside it
    is far to the right of the loop's column: without this,
    ``report.capacity = measure()  # what the cell held`` gave its note to the
    loop above it rather than to the assignment it was written on.
    """
    last = _last_span(block)
    if last is None:
        return []
    stranded = []
    line = last[2] + 1
    while line in marks and marks[line][0] > owner[1] and _only_comment(lines, line):
        stranded.append(_note(line, marks.pop(line)))
        line += 1
    return stranded


def _only_comment(lines: list[str], line: int) -> bool:
    """Return whether a line holds nothing but a comment."""
    return 1 <= line <= len(lines) and lines[line - 1].lstrip().startswith("#")


def name_spans(doc: Any, *, file: str = "") -> Any:
    """Return *doc* with each span's four numbers named.

    Parameters
    ----------
    doc : dict or list or scalar
        A ``CompactDoc``, whose spans are ``[line, col, end_line, end_col]``.
    file : str, optional
        Recorded in each span, since a position means nothing without it.

    Returns
    -------
    dict or list or scalar
        A new document.

    Notes
    -----
    Two shapes for one fact, which is worth stating rather than hiding. The
    editor holds a span as four numbers because it patches source with them and
    reads them by position. A document that carries meaning cannot: a bare
    array says which four numbers, never which is the line and which the
    column, and a consumer has to know the order by convention. The plan and
    the def-use graph already name them, so naming them here is what keeps one
    spelling across the whole document rather than two.
    """
    if isinstance(doc, list):
        return [name_spans(item, file=file) for item in doc]
    if not isinstance(doc, dict):
        return doc

    named = {key: name_spans(value, file=file) for key, value in doc.items() if key != "span"}
    span = doc.get("span")
    if isinstance(span, list) and len(span) == 4:
        start_line, start_col, end_line, end_col = span
        named["span"] = {
            "file": file,
            "start_line": start_line,
            "start_col": start_col,
            "end_line": end_line,
            "end_col": end_col,
        }
    elif span is not None:
        named["span"] = name_spans(span, file=file)
    return named


def _span(doc: dict[str, Any]) -> list[Any]:
    """Return the four-element compact span for *doc*."""
    return [
        doc.get("lineno"),
        doc.get("col_offset"),
        doc.get("end_lineno"),
        doc.get("end_col_offset"),
    ]


def _shorthand(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Return the one-key form for *doc*, or None if it needs the long form.

    A node qualifies only when it carries nothing beyond its single meaningful
    field, so an annotated or collapsed node is never silently flattened.
    """
    node_type = doc.get("_type")
    # None-valued fields are dropped by the encoder anyway, so they must not
    # stop a node qualifying for a shorthand. `kind` carries the u-prefix of a
    # u-string and is almost always null; dropping it outright lost `u''`.
    plain = {key for key, value in doc.items() if value is not None} - _DROP - {"_type"}
    if node_type == "Constant" and plain <= {"value"}:
        return {"literal": doc.get("value")}
    if node_type == "Name" and plain <= {"id"}:
        return {"var": doc.get("id")}
    return None


def _encode_long(doc: dict[str, Any], *, keep_spans: bool) -> dict[str, Any]:
    """Encode a node that does not qualify for a shorthand."""
    node_type = doc.get("_type")
    node: dict[str, Any] = {"@type": node_type} if node_type else {}
    for key, value in doc.items():
        if key in _DROP or key == "_type":
            continue
        if key == "args" and _is_arguments(value):
            node.update(_encode_signature(value, keep_spans=keep_spans))
            continue
        if key == "names" and doc.get("_type") in ("Import", "ImportFrom"):
            node[key] = _encode_implied(value, key, keep_spans=keep_spans)
            continue
        if key in _OPERATOR_FIELDS:
            node[key] = _encode_operator(value)
            continue
        if key == "keyword_arguments" and isinstance(value, dict):
            # The keys here are the author's parameter names, not node fields,
            # so the drop list must not touch them. `optimize.shgo(n=256)`
            # lost its argument because `n` is a legacy AST field name.
            node[key] = {name: encode(item, keep_spans=keep_spans) for name, item in value.items()}
            continue
        encoded = encode(value, keep_spans=keep_spans)
        if encoded is None or (isinstance(encoded, list) and not encoded):
            continue
        node[key] = encoded
    if keep_spans and "lineno" in doc:
        node["span"] = _span(doc)
    return node


def encode(doc: Any, *, keep_spans: bool = False) -> Any:
    """Encode an ``AstDoc`` into the compact form.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc``, from ``ast2json`` or from the elision stage.
    keep_spans : bool, optional
        Keep a ``span`` array. The editor addresses edits by span
        and the trace overlay attributes events by span, so without it there is
        no join key between the editor, the trace and the source. Costs about
        two percentage points of size, so the RDF projection leaves it off.

    Returns
    -------
    dict or list
        A ``CompactDoc``.

    Notes
    -----
    Rules: ``_type`` becomes ``type``; a bare ``Constant`` becomes
    ``{"literal": value}``; a bare ``Name`` becomes ``{"var": id}``; an
    operator becomes its bare name; ``ctx``, positions, nulls, empty lists and
    the derivable orderings are dropped.
    """
    if isinstance(doc, list):
        return [encode(item, keep_spans=keep_spans) for item in doc]
    if not isinstance(doc, dict):
        return doc

    node = _shorthand(doc)
    if node is None:
        return _encode_long(doc, keep_spans=keep_spans)

    if keep_spans and "lineno" in doc:
        node["span"] = _span(doc)
    return node


def _encode_signature(value: dict[str, Any], *, keep_spans: bool) -> dict[str, Any]:
    """Splice the signature's slots up into the function itself.

    So a parameter list reads as ``args: [...]`` rather than as
    ``args: {"@type": "arguments", "args": [...]}``.
    """
    out: dict[str, Any] = {}
    for slot, held in value.items():
        if slot == "_type":
            continue
        encoded = (
            _encode_implied(held, slot, keep_spans=keep_spans)
            if slot in _ARG_FIELDS
            else encode(held, keep_spans=keep_spans)
        )
        if encoded is None or (isinstance(encoded, list) and not encoded):
            continue
        out[slot] = encoded
    return out


def _is_arguments(value: Any) -> bool:
    """Return whether *value* is the signature wrapper."""
    return isinstance(value, dict) and value.get("_type") == "arguments"


def _encode_implied(value: Any, field: str, *, keep_spans: bool) -> Any:
    """Write a node without repeating a type the grammar already fixes.

    Everything in a signature slot is an ``arg``; everything in an import's
    ``names`` is an ``alias``. Saying so adds nothing, and one carrying only
    its own name becomes that name.
    """
    node_type, naming_field = _IMPLIED_TYPES[field]
    if isinstance(value, list):
        return [_encode_implied(item, field, keep_spans=keep_spans) for item in value]
    if not isinstance(value, dict) or value.get("_type") != node_type:
        return encode(value, keep_spans=keep_spans)
    out = {
        key: encode(held, keep_spans=keep_spans)
        for key, held in value.items()
        if key not in _DROP and key != "_type" and held is not None
    }
    return out[naming_field] if set(out) == {naming_field} else out


def _decode_implied(value: Any, field: str) -> Any:
    """Rebuild a node whose type the grammar implies."""
    node_type, naming_field = _IMPLIED_TYPES[field]
    cls = getattr(ast, node_type)
    if isinstance(value, list):
        return [_decode_implied(item, field) for item in value]
    if isinstance(value, str):
        value = {naming_field: value}
    if not isinstance(value, dict) or "@type" in value:
        return decode(value)
    return cls(**{name: decode(value[name]) if name in value else None for name in cls._fields})


def _decode_arguments(node: dict[str, Any]) -> ast.arguments:
    """Rebuild the signature wrapper from the slots spliced into its parent."""
    slots: dict[str, Any] = {}
    for field in _ARGUMENT_FIELDS:
        if field not in node:
            slots[field] = [] if field in _LIST_FIELDS else None
        elif field in _ARG_FIELDS:
            slots[field] = _decode_implied(node[field], field)
        else:
            slots[field] = decode(node[field])
    return ast.arguments(**slots)


def _encode_operator(value: Any) -> Any:
    """Write an operator as its bare name.

    ``{"type": "Add"}`` carries nothing but the name, and ``i += 1`` spends
    three nodes on saying "plus". An operator node has no fields at all, so
    the name is the whole of it.
    """
    if isinstance(value, list):
        return [_encode_operator(item) for item in value]
    if isinstance(value, dict) and "_type" in value:
        return value["_type"]
    return value


def _decode_operator(value: Any) -> Any:
    """Rebuild an operator node from its bare name."""
    if isinstance(value, list):
        return [_decode_operator(item) for item in value]
    if isinstance(value, str):
        return getattr(ast, value)()
    return decode(value)


def _rewrap(items: Any) -> Any:
    """Put back the ``Expr`` wrappers elision dropped.

    Which items in a body need one is derivable — anything that is not itself
    a statement — so the wrapper costs nothing to drop and nothing to restore.
    """
    if not isinstance(items, list):
        return items
    return [ast.Expr(value=item) if isinstance(item, ast.expr) else item for item in items]


def _is_ast_node(node: dict[str, Any]) -> bool:
    """Return whether ``type`` names a syntax node rather than a class.

    Both forms use ``type``, which is the point: one key means "what this
    is". They are told apart by whether the name belongs to the ``ast``
    module, so a collapsed ``ChargeParam`` and a ``While`` never collide.
    """
    declared = node.get("@type")
    return isinstance(declared, str) and isinstance(getattr(ast, declared, None), type)


def _decode_collapsed(node: dict[str, Any]) -> ast.Call:
    """Rebuild the constructor call a collapsed node stands for.

    The compact editor form of a typed constructor is its class name and its
    data and nothing else. Regenerating code has to start from exactly that
    document, so the decoder recognises it rather than requiring the caller to
    undo the collapse first.

    The name comes from ``awl.collapse``: which key names the class is one
    decision, and two implementations of it would drift.
    """
    from awl.collapse import RESERVED, callee_of

    name = callee_of(node)
    if name is None:
        raise ValueError("collapsed node names no local class, so no constructor can be rebuilt")
    keywords = [
        ast.keyword(
            arg=key,
            value=decode(value) if isinstance(value, dict) else ast.Constant(value=value),
        )
        for key, value in node.items()
        if key not in RESERVED
    ]
    return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[], keywords=keywords)


def decode(node: Any) -> Any:
    """Decode the compact form back into a live AST node.

    Parameters
    ----------
    node : dict or list
        A ``CompactDoc``.

    Returns
    -------
    ast.AST or list
        Ready for :func:`ast.fix_missing_locations` and :func:`ast.unparse`.

    Notes
    -----
    Every field of the target class is rebuilt from ``cls._fields``, which is
    what makes the encoder's omissions safe. Copying only the present keys
    works on a recent interpreter and breaks on an older one: 3.11 raises
    ``AttributeError`` unparsing a ``Module`` with no ``type_ignores`` where
    3.13 returns the source.
    """
    if isinstance(node, list):
        return [decode(item) for item in node]
    if not isinstance(node, dict):
        return node

    if "@type" in node and not _is_ast_node(node):
        return _decode_collapsed(node)
    # Minus the drop list, because a shorthand can arrive carrying a
    # materialized ordering: renumbering a statement list stamps `order` onto
    # every item, and a docstring is an item. Reading that as a typed node
    # asked a literal for its `@type` and raised, which made adding a step to
    # any body holding a docstring fail on the way back out.
    plain = set(node) - _DROP
    if "literal" in node and plain <= {"literal", *_SHORTHAND_EXTRA}:
        from awl.astdoc import from_doc

        return ast.Constant(value=from_doc(node["literal"]))
    if "var" in node and plain <= {"var", *_SHORTHAND_EXTRA}:
        return ast.Name(id=node["var"], ctx=ast.Load())

    from awl.elide import unfold_node

    node = unfold_node(node, type_key="@type")
    cls = getattr(ast, node["@type"])
    return cls(**{field: _decode_field(node, cls, field) for field in cls._fields})


def _decode_field(node: dict[str, Any], cls: type, field: str) -> Any:
    """Rebuild one field, supplying what the encoder was able to leave out."""
    if field == "args" and node["@type"] in _SIGNATURE_HOLDERS:
        return _decode_arguments(node)
    if field not in node:
        if field == "ctx":
            return ast.Load()
        return [] if field in _LIST_FIELDS else None
    if field == "names" and node["@type"] in ("Import", "ImportFrom"):
        return _decode_implied(node[field], field)
    if field in _OPERATOR_FIELDS:
        return _decode_operator(node[field])
    decoded = decode(node[field])
    return _rewrap(decoded) if field in ORDERED_FIELDS else decoded


def dumps(doc: Any, *, width: int = 88, indent: int = 1, _depth: int = 0) -> str:
    """Serialize a compact document, inlining whatever fits.

    Parameters
    ----------
    doc : Any
        A ``CompactDoc``, or any JSON-serializable value.
    width : int, optional
        The column a line may reach before its structure is broken open.
    indent : int, optional
        Spaces per level.

    Returns
    -------
    str
        JSON in which a small structure stays on one line and a large one
        breaks.

    Notes
    -----
    ``json.dumps(indent=...)`` puts every element of every structure on its own
    line, so ``{"var": "i"}`` costs three lines and a two-argument call costs a
    page. That is not more readable, only taller: the shape of a node is
    easiest to see when the node fits on one line.
    """
    pad = " " * (indent * _depth)
    inner = " " * (indent * (_depth + 1))

    if isinstance(doc, dict):
        if not doc:
            return "{}"
        flat = (
            "{"
            + ", ".join(json.dumps(key) + ": " + dumps(value, width=width, indent=0) for key, value in doc.items())
            + "}"
        )
        if len(pad) + len(flat) <= width and NEWLINE not in flat:
            return flat
        parts = [
            inner + json.dumps(key) + ": " + dumps(value, width=width, indent=indent, _depth=_depth + 1)
            for key, value in doc.items()
        ]
        return "{" + NEWLINE + ("," + NEWLINE).join(parts) + NEWLINE + pad + "}"

    if isinstance(doc, list):
        if not doc:
            return "[]"
        flat = "[" + ", ".join(dumps(item, width=width, indent=0) for item in doc) + "]"
        if len(pad) + len(flat) <= width and NEWLINE not in flat:
            return flat
        parts = [inner + dumps(item, width=width, indent=indent, _depth=_depth + 1) for item in doc]
        return "[" + NEWLINE + ("," + NEWLINE).join(parts) + NEWLINE + pad + "]"

    return json.dumps(doc)
