"""Compact AST codec: the editor model for AWL-LD workflows.

Both ends speak ``AstDoc``, so this composes with the elision stage. An earlier
draft dispatched on live ``ast.AST`` objects while its contract claimed
``AstDoc``, which meant the two stages could not chain at all.
"""

from __future__ import annotations

import ast
from typing import Any

__all__ = ["decode", "encode"]

# Fields the ast constructors require as sequences. Anything absent from a
# compact document is rebuilt as an empty list, which is what lets the encoder
# drop them.
_LIST_FIELDS = frozenset({
    "args",
    "bases",
    "body",
    "comparators",
    "decorator_list",
    "defaults",
    "elts",
    "finalbody",
    "generators",
    "handlers",
    "items",
    "keywords",
    "kw_defaults",
    "kwonlyargs",
    "names",
    "ops",
    "orelse",
    "posonlyargs",
    "targets",
    "type_ignores",
    "type_params",
    "values",
})

# Derivable or positional; never carried.
_DROP = frozenset({
    "col_offset",
    "ctx",
    "end_col_offset",
    "end_lineno",
    "kind",
    "lineno",
    "n",
    "s",
    "type_comment",
})

# The orderings materialized by the elision stage, plus the optional span, ride
# alongside a shorthand node rather than forcing it back to the long form.
_CARRY = ("order", "argumentIndex", "argumentName")
_SHORTHAND_EXTRA = frozenset({"@", *_CARRY})


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
    plain = set(doc) - _DROP - {"_type", *_CARRY}
    if node_type == "Constant" and plain <= {"value"}:
        return {"c": doc.get("value")}
    if node_type == "Name" and plain <= {"id"}:
        return {"$": doc.get("id")}
    return None


def _encode_long(doc: dict[str, Any], *, keep_spans: bool) -> dict[str, Any]:
    """Encode a node that does not qualify for a shorthand."""
    node_type = doc.get("_type")
    node: dict[str, Any] = {"_": node_type} if node_type else {}
    for key, value in doc.items():
        if key in _DROP or key == "_type":
            continue
        encoded = encode(value, keep_spans=keep_spans)
        if encoded is None or (isinstance(encoded, list) and not encoded):
            continue
        node[key] = encoded
    if keep_spans and "lineno" in doc:
        node["@"] = _span(doc)
    return node


def encode(doc: Any, *, keep_spans: bool = False) -> Any:
    """Encode an ``AstDoc`` into the compact form.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc``, from ``ast2json`` or from the elision stage.
    keep_spans : bool, optional
        Keep a compact ``"@"`` span array. The editor addresses edits by span
        and the trace overlay attributes events by span, so without it there is
        no join key between the editor, the trace and the source. Costs about
        two percentage points of size, so the RDF projection leaves it off.

    Returns
    -------
    dict or list
        A ``CompactDoc``.

    Notes
    -----
    Rules: ``_type`` becomes ``_``; a bare ``Constant`` becomes ``{"c": value}``;
    a bare ``Name`` becomes ``{"$": id}``; ``ctx``, positions, nulls and empty
    lists are dropped. Orderings are carried through unchanged.
    """
    if isinstance(doc, list):
        return [encode(item, keep_spans=keep_spans) for item in doc]
    if not isinstance(doc, dict):
        return doc

    node = _shorthand(doc)
    if node is None:
        return _encode_long(doc, keep_spans=keep_spans)

    if keep_spans and "lineno" in doc:
        node["@"] = _span(doc)
    for field in _CARRY:
        if field in doc:
            node[field] = doc[field]
    return node


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

    if "@type" in node and "_" not in node:
        return _decode_collapsed(node)
    if "c" in node and set(node) <= {"c", *_SHORTHAND_EXTRA}:
        return ast.Constant(value=node["c"])
    if "$" in node and set(node) <= {"$", *_SHORTHAND_EXTRA}:
        return ast.Name(id=node["$"], ctx=ast.Load())

    cls = getattr(ast, node["_"])
    kwargs: dict[str, Any] = {}
    for field in cls._fields:
        if field in node:
            kwargs[field] = decode(node[field])
        elif field == "ctx":
            kwargs[field] = ast.Load()
        else:
            kwargs[field] = [] if field in _LIST_FIELDS else None
    return cls(**kwargs)
