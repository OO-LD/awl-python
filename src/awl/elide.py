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

from awl.vocab import FOLDS_KEYWORDS, OPAQUE, ORDERED_FIELDS, TRANSPARENT

__all__ = ["elide", "unfold", "unfold_node"]


def elide(doc: Any, *, profile: str = "ast", source: str = "") -> Any:
    """Apply a cutoff profile to an AST document.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc``.
    profile : str
        One of ``awl.vocab.PROFILES``.
    source : str, optional
        Original text, used to populate ``sourceText`` on opaque nodes. Without
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
            "parserTypeName": node_type,
            "sourceText": _source_text(node, source),
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
    ``argumentName``. That is the code property graph's convention, and it
    means a second language frontend without keyword arguments simply never
    emits -1.
    """
    for position, argument in enumerate(out.get("args", []) or []):
        if isinstance(argument, dict):
            argument["argumentIndex"] = position + 1

    if not folds_keywords:
        return

    folded: dict[str, Any] = {}
    for keyword in out.get("keywords", []) or []:
        if isinstance(keyword, dict) and keyword.get("arg"):
            value = keyword.get("value")
            if isinstance(value, dict):
                value["argumentName"] = keyword["arg"]
                value["argumentIndex"] = -1
            folded[keyword["arg"]] = value
    if folded:
        out["keywordArguments"] = folded
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
_ORDERING = ("argumentName", "argumentIndex")


def unfold_node(node: dict[str, Any]) -> dict[str, Any]:
    """Reverse keyword folding for one node.

    Parameters
    ----------
    node : dict
        A node that may carry ``keywordArguments``.

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
    folded = node.get("keywordArguments")
    if not isinstance(folded, dict):
        return node
    out = {key: value for key, value in node.items() if key != "keywordArguments"}
    position = {key: node[key] for key in _POSITION if key in node}
    out["keywords"] = [
        {
            "_type": "keyword",
            "arg": name,
            "value": {k: v for k, v in value.items() if k not in _ORDERING} if isinstance(value, dict) else value,
            **position,
        }
        for name, value in folded.items()
    ]
    return out


def unfold(doc: Any) -> Any:
    """Reverse keyword folding throughout a document.

    Parameters
    ----------
    doc : dict or list
        An ``AstDoc`` produced by :func:`elide`.

    Returns
    -------
    dict or list
        A document whose calls carry ``keywords`` again, ready to unparse.
    """
    if isinstance(doc, list):
        return [unfold(item) for item in doc]
    if not isinstance(doc, dict):
        return doc
    return unfold_node({key: unfold(value) for key, value in doc.items()})
