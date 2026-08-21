"""Profile-driven cutoff: order, fold, elide.

Three behaviours, not one. **Order** materializes the two orderings, so
statement sequence is queryable without walking an RDF collection. **Fold**
merges a keyword argument into its call while keeping its name. **Elide**
unwraps a transparent wrapper into its parent and reduces an opaque expression
to a single node holding its source text.

The distinction between folding and eliding a keyword is load-bearing.
Treating ``keyword`` as transparent and splicing out its value discards the
argument name, turning ``charge(ChargeParam(target_voltage=4.2, c_rate=0.23))``
into ``ChargeParam(4.2, 0.23)``. That is a semantic change rather than a
formatting one, and it also leaves the collapse with nothing to match on.
"""

from __future__ import annotations

from typing import Any

from awl.vocab import FOLDS_KEYWORDS, OPAQUE, ORDERED_FIELDS, TRANSPARENT, statement_types

__all__ = ["elide", "rewrap_statements", "unfold", "unfold_node"]


def elide(doc: Any, *, profile: str = "ast", source: str = "") -> Any:
    """Apply a cutoff profile to an AST document.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc``.
    profile : str
        One of ``awl.vocab.PROFILES``.
    source : str, optional
        Original text, used to populate ``source_text`` on opaque nodes. Without
        it an opaque node keeps its type but loses its expression.

    Returns
    -------
    dict or list
        A new document; the input is not mutated.

    Raises
    ------
    KeyError
        If the profile is unknown, rather than silently doing nothing.
    """
    return _walk(doc, TRANSPARENT[profile], OPAQUE[profile], FOLDS_KEYWORDS[profile], source)


def _walk(node: Any, transparent, opaque, folds_keywords: bool, source: str) -> Any:
    """Rewrite one node and its children under the active profile."""
    if isinstance(node, list):
        return [_walk(item, transparent, opaque, folds_keywords, source) for item in node]
    if not isinstance(node, dict):
        return node

    node_type = node.get("_type")

    if node_type in opaque:
        # Following the code property graph's PARSER_TYPE_NAME: the
        # language-specific label rides as a property, never as the node type.
        return {
            "_type": "Call",
            "parser_type_name": node_type,
            "source_text": _source_text(node, source),
        }

    out: dict[str, Any] = {}
    for key, value in node.items():
        walked = _walk(value, transparent, opaque, folds_keywords, source)
        if isinstance(walked, list) and not walked:
            continue
        out[key] = walked

    _materialize_order(out)
    if node_type == "Call":
        _index_arguments(out, folds_keywords)

    if node_type in transparent:
        payload = out.get("value")
        if payload is not None:
            if isinstance(payload, dict) and "order" in out:
                payload["order"] = out["order"]
            return payload
    return out


def _materialize_order(out: dict[str, Any]) -> None:
    """Give every statement its sibling slot.

    ``@container: @list`` preserves order in RDF but yields members rather than
    positions: recovering an index means counting ``rdf:rest`` hops, and SPARQL
    property paths cannot count. This integer is the query surface.
    """
    for field in ORDERED_FIELDS:
        sequence = out.get(field)
        if isinstance(sequence, list):
            for position, child in enumerate(sequence):
                if isinstance(child, dict):
                    child["order"] = position


def _index_arguments(out: dict[str, Any], folds_keywords: bool) -> None:
    """Bind arguments to parameters, and fold keywords preserving their names.

    Positional arguments are numbered from 1; 0 is reserved for an implicit
    receiver, and -1 marks a named argument, which then also carries
    ``argument_name``. That is the code property graph's convention, and it
    means a second language frontend without keyword arguments simply never
    emits -1.
    """
    for position, argument in enumerate(out.get("args", []) or []):
        if isinstance(argument, dict):
            argument["argument_index"] = position + 1

    if not folds_keywords:
        return

    keywords = out.get("keywords", []) or []
    if any(isinstance(item, dict) and not item.get("arg") for item in keywords):
        # A `**kwargs` entry has no name to fold under, and its position among
        # the named arguments is significant: `f(**rest, a=1)` and `f(a=1,
        # **rest)` are different calls. A map cannot express that, so the call
        # keeps its list. Folding is a compaction, and skipping it costs
        # nothing but bytes.
        return

    folded: dict[str, Any] = {}
    unfoldable: list[Any] = []
    for keyword in keywords:
        if isinstance(keyword, dict) and keyword.get("arg"):
            value = keyword.get("value")
            if isinstance(value, dict):
                value["argument_name"] = keyword["arg"]
                value["argument_index"] = -1
            folded[keyword["arg"]] = value
        else:
            # `**kwargs` is a keyword with no name, so it has no key to fold
            # under. Dropping the whole list once anything folded deleted it
            # silently: `f(a=1, **rest)` regenerated as `f(a=1)`.
            unfoldable.append(keyword)
    if folded:
        out["keyword_arguments"] = folded
        if unfoldable:
            out["keywords"] = unfoldable
        else:
            out.pop("keywords", None)


def _source_text(node: dict[str, Any], source: str) -> str:
    """Return the original text of an opaque node, or "" when unavailable."""
    if not source or "lineno" not in node:
        return ""
    lines = source.splitlines()
    start = node.get("lineno")
    end = node.get("end_lineno", start)
    if not start or start > len(lines):
        return ""
    if start == end:
        return lines[start - 1][node.get("col_offset", 0) : node.get("end_col_offset")]
    return "\n".join(lines[start - 1 : end])


#: Position keys copied onto a reconstructed keyword node.
_POSITION = ("lineno", "col_offset", "end_lineno", "end_col_offset")

#: Markers folding adds. They are derivable from the restored keyword list, so
#: carrying them back would duplicate what the structure already says.
_ORDERING = ("argument_name", "argument_index")


def unfold_node(node: dict[str, Any], *, type_key: str = "_type") -> dict[str, Any]:
    """Reverse keyword folding for one node.

    Parameters
    ----------
    node : dict
        A node that may carry ``keyword_arguments``.
    type_key : str, optional
        The key naming a node type. The compact form spells it ``type`` and
        the intermediate form ``_type``; parameterising it keeps one
        implementation of how folding reverses, rather than two that drift.

    Returns
    -------
    dict
        The node with its ``keywords`` list restored, or unchanged.

    Notes
    -----
    Folding is a rewrite, not a loss, and this is what makes that true. Every
    profile folds because of it, including the faithful one: without a working
    inverse the profile that regenerates code could not fold, and the
    constructor collapse could never fire where it is most useful.
    """
    folded = node.get("keyword_arguments")
    if not isinstance(folded, dict):
        return node
    out = {key: value for key, value in node.items() if key != "keyword_arguments"}
    position = {key: node[key] for key in _POSITION if key in node}
    # Anything already here had no name to fold under, `**kwargs` being the
    # only case. Overwriting the list rather than extending it dropped it.
    survived = list(out.get("keywords", []) or [])
    out["keywords"] = [
        {
            type_key: "keyword",
            "arg": name,
            "value": {k: v for k, v in value.items() if k not in _ORDERING} if isinstance(value, dict) else value,
            **position,
        }
        for name, value in folded.items()
    ] + survived
    return out


def rewrap_statements(node: dict[str, Any]) -> dict[str, Any]:
    """Put back the ``Expr`` wrappers that elision dropped.

    Python needs a statement to hold an expression in a body. *Which* items
    need one is entirely derivable — anything in a statement list that is not
    itself a statement — so dropping the wrapper costs nothing and restoring
    it needs no record of what was removed. That is what makes ``Expr``
    elidable on the profile that regenerates code, where a lossy elision would
    not be.
    """
    statements = statement_types()
    out = dict(node)
    for field in ORDERED_FIELDS:
        items = out.get(field)
        if not isinstance(items, list):
            continue
        out[field] = [
            item
            if not isinstance(item, dict) or item.get("_type") in statements or "_type" not in item
            else {
                "_type": "Expr",
                "value": item,
                **{key: item[key] for key in _POSITION if key in item},
            }
            for item in items
        ]
    return out


def unfold(doc: Any) -> Any:
    """Restore everything elision rewrote reversibly.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc`` produced by :func:`elide`.

    Returns
    -------
    dict or list
        A document whose calls carry ``keywords`` again and whose bodies carry
        their statement wrappers, ready to unparse.
    """
    if isinstance(doc, list):
        return [unfold(item) for item in doc]
    if not isinstance(doc, dict):
        return doc
    return rewrap_statements(unfold_node({key: unfold(value) for key, value in doc.items()}))
