"""Faithful conversion between a Python syntax tree and plain JSON data.

Written rather than taken from a library because the obvious library is lossy
in a way that cannot be repaired downstream. ``ast2json`` renders every
constant through ``str``, so ``b'ab'``, ``...`` and ``1j`` all arrive as the
strings ``"ab"``, ``"..."`` and ``"1j"``, indistinguishable from a plain
string literal. Measured across the standard library that alone accounts for
around a fifth of all files failing to regenerate.

A constant whose type JSON cannot express is therefore tagged, and the tag is
what makes the round trip total rather than merely usual.
"""

from __future__ import annotations

import ast
import base64
from typing import Any

__all__ = ["from_doc", "to_doc"]

#: Tag keys for constants JSON has no native form for. Each is a single-key
#: object, which cannot be confused with a string, a number or a node.
_BYTES = "@bytes"
_COMPLEX = "@complex"
_ELLIPSIS = "@ellipsis"


def _encode_constant(value: Any) -> Any:
    """Return a JSON form that distinguishes every constant type."""
    if isinstance(value, bytes):
        return {_BYTES: base64.b64encode(value).decode("ascii")}
    if isinstance(value, complex):
        return {_COMPLEX: [value.real, value.imag]}
    if value is Ellipsis:
        return {_ELLIPSIS: True}
    return value


def _decode_constant(value: Any) -> Any:
    """Reverse :func:`_encode_constant`."""
    if isinstance(value, dict):
        if _BYTES in value:
            return base64.b64decode(value[_BYTES])
        if _COMPLEX in value:
            real, imaginary = value[_COMPLEX]
            return complex(real, imaginary)
        if _ELLIPSIS in value:
            return Ellipsis
    return value


def to_doc(node: Any) -> Any:
    """Convert a syntax tree to plain JSON data.

    Parameters
    ----------
    node : ast.AST or list or scalar
        Usually the result of :func:`ast.parse`.

    Returns
    -------
    dict or list or scalar
        An ``AstDoc``: every node becomes an object with ``_type`` and its
        declared fields, plus its position attributes.
    """
    if isinstance(node, ast.AST):
        out: dict[str, Any] = {"_type": type(node).__name__}
        for field in node._fields:
            out[field] = to_doc(getattr(node, field, None))
        for attribute in node._attributes:
            if hasattr(node, attribute):
                out[attribute] = getattr(node, attribute)
        return out
    if isinstance(node, list):
        return [to_doc(item) for item in node]
    return _encode_constant(node)


def from_doc(doc: Any) -> Any:
    """Rebuild a syntax tree from plain JSON data.

    Parameters
    ----------
    doc : dict or list or scalar
        An ``AstDoc``.

    Returns
    -------
    ast.AST or list or scalar
        Ready for :func:`ast.fix_missing_locations` and :func:`ast.unparse`.

    Notes
    -----
    Every declared field is rebuilt, defaulting a sequence to an empty list, so
    a document that omitted a field still produces a usable node.
    """
    if isinstance(doc, list):
        return [from_doc(item) for item in doc]
    if not isinstance(doc, dict):
        return doc
    if not set(doc) - {_BYTES, _COMPLEX, _ELLIPSIS}:
        return _decode_constant(doc)
    if "_type" not in doc:
        return doc

    cls = getattr(ast, doc["_type"])
    kwargs: dict[str, Any] = {}
    for field in cls._fields:
        if field in doc:
            kwargs[field] = _decode_constant(from_doc(doc[field]))
        else:
            kwargs[field] = [] if _is_sequence(cls, field) else None
    node = cls(**kwargs)
    for attribute in cls._attributes:
        if attribute in doc:
            setattr(node, attribute, doc[attribute])
    return node


def _is_sequence(cls: type, field: str) -> bool:
    """Return whether the grammar declares *field* as a sequence."""
    return "list" in str(getattr(cls, "__annotations__", {}).get(field, ""))
