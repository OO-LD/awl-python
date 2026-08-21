"""The headless editing model: palette, edits, and domain validation.

Pure functions over a compact document. No browser, no rendering. Every edit
returns a new document *and* a patch that can be applied to source, so the
visual and textual representations never diverge: an edit that returned only
the new document would force the writer to diff two trees and guess which
source range changed.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "add_step",
    "delete_step",
    "palette",
    "reorder",
    "set_literal",
    "validate_domain",
]

#: Properties whose enum constraints define what may be placed. Extending this
#: is a deliberate change: each entry is a claim about what a domain profile is
#: allowed to restrict.
_PALETTE_SOURCES = (("_type", "construct"), ("_", "construct"), ("callee", "callee"))


def _collect_enum(node: Any, prop: str, out: list[str]) -> None:
    """Gather enum values for *prop* anywhere in the schema, including $defs."""
    if isinstance(node, list):
        for item in node:
            _collect_enum(item, prop, out)
    elif isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get(prop), dict):
            values = properties[prop].get("enum")
            if isinstance(values, list):
                out.extend(values)
        for value in node.values():
            _collect_enum(value, prop, out)


def palette(schema: dict[str, Any], type_schemas: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Derive the placeable node types.

    Parameters
    ----------
    schema : dict
        The workflow domain schema. Its ``enum`` constraints say what is legal.
    type_schemas : list of dict, optional
        OO-LD class schemas. Each contributes a typed entry carrying the fields
        its form needs, so a ``ChargeParam`` entry already knows its fields,
        their ranges and their widgets.

    Returns
    -------
    list of dict
        Each has ``name`` and ``kind``, deduplicated, in schema order. Empty
        when the schema declares no enum, which means the domain permits
        nothing rather than everything.

    Notes
    -----
    Read from ordinary JSON Schema ``enum`` constraints, with no vendor
    keyword. A document here *is* the syntax tree as JSON, so plain JSON Schema
    already expresses the restriction. That matters twice over: any standard
    validator enforces it, where a vendor keyword would have to be ignored by
    a generic validator and would turn the constraint into a hint; and the
    schema stays one artefact rather than encoding the same rule twice.

    The two sources are both needed. The domain schema alone gives a list of
    names; the class schemas are what make an entry usable as a form.
    """
    seen: set[tuple[str, str]] = set()
    entries: list[dict[str, Any]] = []
    for prop, kind in _PALETTE_SOURCES:
        found: list[str] = []
        _collect_enum(schema, prop, found)
        for name in found:
            if (kind, name) not in seen:
                seen.add((kind, name))
                entries.append({"name": name, "kind": kind})

    for type_schema in type_schemas or []:
        name = type_schema.get("title") or type_schema.get("$id", "")
        if (("type", name)) in seen:
            continue
        seen.add(("type", name))
        entries.append({
            "name": name,
            "kind": "type",
            "fields": dict(type_schema.get("properties", {})),
            "declaredTypes": list(type_schema.get("x-oold-instance-rdf-type", [])),
        })
    return entries


def _descend(doc: dict[str, Any], path: list[Any]) -> Any:
    """Return the value at *path*, raising a locatable error if it is absent."""
    target: Any = doc
    for step, key in enumerate(path):
        try:
            target = target[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(f"no node at {path[: step + 1]}") from exc
    return target


def _renumber(steps: list[dict[str, Any]]) -> None:
    """Rewrite ``order`` to match list position.

    ``order`` is the query surface, so a structural edit that moved list
    position without updating it would leave the RDF saying the opposite of
    the document.
    """
    for position, step in enumerate(steps):
        if isinstance(step, dict):
            step["order"] = position


def _unparse(node: dict[str, Any]) -> str:
    """Return the source text for a compact node."""
    import ast

    from awl.compact import decode

    return ast.unparse(ast.fix_missing_locations(decode(node)))


def _structural(operation: str, path: list[Any], **extra: Any) -> list[dict[str, Any]]:
    """Return a patch the write-back stage must route through libcst.

    Span splicing has no opinion about which comment belongs to which
    statement, so a moved node cannot carry its own trivia. Marking the tier
    here keeps the caller from having to know which mechanism applies.
    """
    return [{"kind": "structural", "operation": operation, "path": list(path), **extra}]


def set_literal(
    doc: dict[str, Any], *, path: list[Any], value: Any, span: dict[str, int]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replace a literal, returning the new document and a source patch.

    Parameters
    ----------
    doc : dict
        A compact document. Not mutated.
    path : list
        Keys and indices locating the literal node.
    value : Any
        The new literal value.
    span : dict
        ``start`` and ``end`` character offsets of the literal in the source.

    Returns
    -------
    tuple
        The new document, and a patch that can be applied by span rather than
        by regenerating the file.
    """
    out = copy.deepcopy(doc)
    target = _descend(out, path[:-1]) if path[:-1] else out
    target[path[-1]] = {"literal": value}
    return out, [{"start": span["start"], "end": span["end"], "text": repr(value)}]


def add_step(
    doc: dict[str, Any], *, into: list[Any], node: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Append a step to a statement list.

    Parameters
    ----------
    doc : dict
        A compact document. Not mutated.
    into : list
        Path to the statement list, e.g. ``["body"]``.
    node : dict
        The compact node to append.

    Returns
    -------
    tuple
        The new document with ``order`` renumbered, and a structural patch.
    """
    out = copy.deepcopy(doc)
    steps = _descend(out, into)
    steps.append(copy.deepcopy(node))
    _renumber(steps)
    return out, _structural("insert", into, code=_unparse(node))


def delete_step(doc: dict[str, Any], *, path: list[Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Remove a step, renumbering the rest.

    Parameters
    ----------
    doc : dict
        A compact document. Not mutated.
    path : list
        Path to the step, ending in its index, e.g. ``["body", 0]``.

    Returns
    -------
    tuple
        The new document and a structural patch.
    """
    out = copy.deepcopy(doc)
    steps = _descend(out, path[:-1])
    removed = steps.pop(path[-1])
    _renumber(steps)
    return out, _structural("delete", path, code=_unparse(removed))


def reorder(doc: dict[str, Any], *, path: list[Any], frm: int, to: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Move a step within a statement list.

    Parameters
    ----------
    doc : dict
        A compact document. Not mutated.
    path : list
        Path to the statement list.
    frm, to : int
        Source and destination positions.

    Returns
    -------
    tuple
        The new document with ``order`` renumbered, and a structural patch.
    """
    out = copy.deepcopy(doc)
    steps = _descend(out, path)
    steps.insert(to, steps.pop(frm))
    _renumber(steps)
    return out, _structural("reorder", path, frm=frm, to=to)


def validate_domain(node: dict[str, Any], schema: dict[str, Any]) -> None:
    """Check one node against the workflow domain schema.

    Parameters
    ----------
    node : dict
        The node to check.
    schema : dict
        The workflow domain schema.

    Raises
    ------
    jsonschema.ValidationError
        If the node is not permitted. Deliberately the library's own error and
        not a wrapped one, so the message names the offending enum.
    """
    import jsonschema

    jsonschema.validate(node, schema)
