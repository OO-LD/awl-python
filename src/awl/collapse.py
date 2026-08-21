"""Type-driven collapse of call subtrees into typed nodes, and its inverse.

A call whose callee resolves to an annotated type is rewritten into a single
node interpreted by that type's own context, so the call site carries meaning
without the author writing any linked data.

The mechanism is what is new here, not the goal. Other systems reach the same
semantic target by attaching meaning to a *declared signature*; this rewrites a
*call site's subtree* using the resolved callee's context. Code-indexing
systems keep the call as a call and merely point at the callee.

The collapse is a representation change rather than a projection, so it has an
inverse. Without :func:`expand` an editor could display a workflow and never
write one back.
"""

from __future__ import annotations

from typing import Any

from awl.elide import unfold_node

__all__ = ["RESERVED", "callee_of", "collapse", "expand"]

#: Keys of a collapsed node that are structure rather than field data.
RESERVED = frozenset({"@context", "@type", "@", "_callee", "order"})
_RESERVED = RESERVED


def collapse(
    doc: Any,
    *,
    types: dict[str, Any],
    resolved: dict[str, str],
    embed_context: bool = True,
    keep_spans: bool = False,
) -> Any:
    """Rewrite resolved constructor calls into typed nodes.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc``.
    types : dict
        ``TypeInfo`` keyed by symbol name.
    resolved : dict
        Local name to symbol name. A name absent here is not collapsed, which
        is how an ambiguous binding stays a plain call: a wrong type is worse
        than no type.
    embed_context : bool, optional
        Emit a per-node ``@context``. Turn it off when the document already
        carries a context naming these types, which is the compact form: a
        node is then just its class name and its data.
    keep_spans : bool, optional
        Emit the source span as ``"@"``. Needed only to patch the original
        file in place; regenerating code from the document does not use it.
        Off by default, matching the compact encoder.

    Returns
    -------
    dict or list
        A new document.
    """
    options: dict[str, Any] = {
        "types": types,
        "resolved": resolved,
        "embed_context": embed_context,
        "keep_spans": keep_spans,
    }
    if isinstance(doc, list):
        return [collapse(item, **options) for item in doc]
    if not isinstance(doc, dict):
        return doc

    if doc.get("_type") == "Call":
        callee = doc.get("func", {}).get("id")
        symbol = resolved.get(callee) if callee else None
        info = types.get(symbol) if symbol else None
        if info is not None:
            return _typed_node(doc, info, callee, **options)

    return {key: collapse(value, **options) for key, value in doc.items()}


def _descend(call: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """Leave the call as a call, still collapsing anything nested inside it."""
    return {key: collapse(value, **kw) for key, value in call.items()}


def _typed_node(
    call: dict[str, Any],
    info: dict[str, Any],
    callee: str,
    *,
    embed_context: bool,
    keep_spans: bool,
    **kw: Any,
) -> dict[str, Any]:
    """Build the typed node, keyed on the callee's declared field names.

    Keying on field names rather than on keyword syntax is deliberate: Python
    keyword arguments have no equivalent in most languages, so a syntax-keyed
    collapse would not survive a second frontend even though its output would
    be identical.

    The property namespace comes from the **minted** IRI, which is resolvable.
    A declared type is usually a CURIE against a prefix this package does not
    control, and using it here produces predicates like
    ``ex:ChargeParam#target_voltage``, which validate and join with nothing.
    """
    arguments = call.get("keywordArguments")
    if arguments is None:
        # Keywords have not been folded, so there is nothing to key on.
        return _descend(call, embed_context=embed_context, keep_spans=keep_spans, **kw)

    fields = {field["name"] for field in info["fields"]}
    if not set(arguments) <= fields:
        # An undeclared keyword would have to become an invented property.
        # Silent invention is the failure mode this guards.
        return _descend(call, embed_context=embed_context, keep_spans=keep_spans, **kw)

    # The class name leads, as a bare term. A term resolves through the
    # context, so it is both the name to regenerate and, once mapped, the IRI;
    # the declared CURIEs follow it as co-types.
    node: dict[str, Any] = {"@type": [callee, *(info.get("declaredTypes") or [])]}
    if embed_context:
        node["@context"] = {
            "@vocab": info["identity"]["iri"] + "#",
            callee: info["identity"]["iri"],
        }
    if keep_spans:
        node["@"] = [
            call.get("lineno"),
            call.get("col_offset"),
            call.get("end_lineno"),
            call.get("end_col_offset"),
        ]
    if "order" in call:
        node["order"] = call["order"]

    for name, value in arguments.items():
        if isinstance(value, dict) and value.get("_type") == "Constant":
            node[name] = value.get("value")
        else:
            node[name] = collapse(value, embed_context=embed_context, keep_spans=keep_spans, **kw)
    return node


def expand(node: Any) -> Any:
    """Rebuild a ``Call`` document from a typed node.

    Parameters
    ----------
    node : dict or list
        A document that may contain collapsed nodes.

    Returns
    -------
    dict or list
        An ``AstDoc`` with every typed node turned back into a call.

    Raises
    ------
    ValueError
        If a typed node carries no ``_callee``. Emitting a call with a guessed
        name would be worse than refusing.

    Notes
    -----
    Field insertion order is the keyword order, which JSON objects and Python
    dictionaries both preserve, so the restored call reads as it was written.
    """
    if isinstance(node, list):
        return [expand(item) for item in node]
    if not isinstance(node, dict):
        return node
    callee = callee_of(node)
    if "@type" in node and callee is None:
        raise ValueError(
            "typed node names no local class, so it cannot be expanded; expected a bare term in @type or a _callee"
        )
    if callee is None:
        expanded = {key: expand(value) for key, value in node.items()}
        return unfold_node(expanded)

    span = node.get("@") or [1, 0, 1, 0]
    position = {
        "lineno": span[0],
        "col_offset": span[1],
        "end_lineno": span[2],
        "end_col_offset": span[3],
    }
    keywords = []
    for name, value in node.items():
        if name in _RESERVED:
            continue
        inner = expand(value) if isinstance(value, dict) else {"_type": "Constant", "value": value, **position}
        keywords.append({"_type": "keyword", "arg": name, "value": inner, **position})

    return {
        "_type": "Call",
        "func": {"_type": "Name", "id": callee, "ctx": {"_type": "Load"}, **position},
        "args": [],
        "keywords": keywords,
        **position,
    }


def callee_of(node: dict[str, Any]) -> str | None:
    """Return the local class name a collapsed node names, or None.

    Read from ``@type`` when it carries a bare term. A term resolves through
    the context and is therefore both the class name and, once mapped, the
    IRI; a CURIE or absolute IRI is emitted verbatim and names no local class.
    That distinction is what removes the need for a separate ``_callee``.
    """
    if "_callee" in node:
        return node["_callee"]
    declared = node.get("@type")
    if isinstance(declared, str):
        declared = [declared]
    for candidate in declared or []:
        if isinstance(candidate, str) and ":" not in candidate and "/" not in candidate:
            return candidate
    return None
