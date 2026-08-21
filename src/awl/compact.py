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
from typing import Any

from awl.vocab import ORDERED_FIELDS

__all__ = ["decode", "encode"]


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

# Fields holding `arg` nodes, whose type is likewise fixed by the grammar.
_ARG_FIELDS = frozenset({"args", "posonlyargs", "kwonlyargs", "vararg", "kwarg"})

# Orderings are derivable from array position here and are **not** carried.
# They are materialized in the RDF projection, where position is not
# recoverable: an rdf:List yields members, and SPARQL property paths cannot
# count. Carrying them in this document would duplicate what the array already
# says, and let an editor reorder the array while leaving the numbers stale.
_ORDERINGS = ("order", "argument_index", "argument_name")
_SHORTHAND_EXTRA = frozenset({"span"})


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
            _encode_arg(held, keep_spans=keep_spans) if slot in _ARG_FIELDS else encode(held, keep_spans=keep_spans)
        )
        if encoded is None or (isinstance(encoded, list) and not encoded):
            continue
        out[slot] = encoded
    return out


def _is_arguments(value: Any) -> bool:
    """Return whether *value* is the signature wrapper."""
    return isinstance(value, dict) and value.get("_type") == "arguments"


def _encode_arg(value: Any, *, keep_spans: bool) -> Any:
    """Write a parameter without repeating that it is one.

    Everything in a signature slot is an ``arg``, so the label says nothing.
    A parameter with nothing but a name becomes that name.
    """
    if isinstance(value, list):
        return [_encode_arg(item, keep_spans=keep_spans) for item in value]
    if not isinstance(value, dict) or value.get("_type") != "arg":
        return encode(value, keep_spans=keep_spans)
    out = {
        key: encode(held, keep_spans=keep_spans)
        for key, held in value.items()
        if key not in _DROP and key != "_type" and held is not None
    }
    if set(out) == {"arg"}:
        return out["arg"]
    return out


def _decode_arg(value: Any) -> Any:
    """Rebuild a parameter from its name or its slots."""
    if isinstance(value, list):
        return [_decode_arg(item) for item in value]
    if isinstance(value, str):
        return ast.arg(arg=value, annotation=None, type_comment=None)
    if isinstance(value, dict) and "@type" not in value:
        return ast.arg(
            arg=value.get("arg"),
            annotation=decode(value["annotation"]) if "annotation" in value else None,
            type_comment=None,
        )
    return decode(value)


def _decode_arguments(node: dict[str, Any]) -> ast.arguments:
    """Rebuild the signature wrapper from the slots spliced into its parent."""
    slots: dict[str, Any] = {}
    for field in _ARGUMENT_FIELDS:
        if field not in node:
            slots[field] = [] if field in _LIST_FIELDS else None
        elif field in _ARG_FIELDS:
            slots[field] = _decode_arg(node[field])
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
    if "literal" in node and set(node) <= {"literal", *_SHORTHAND_EXTRA}:
        from awl.astdoc import from_doc

        return ast.Constant(value=from_doc(node["literal"]))
    if "var" in node and set(node) <= {"var", *_SHORTHAND_EXTRA}:
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
    if field in _OPERATOR_FIELDS:
        return _decode_operator(node[field])
    decoded = decode(node[field])
    return _rewrap(decoded) if field in ORDERED_FIELDS else decoded
