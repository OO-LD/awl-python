"""Inference: bind names to identities, and say how sure we are.

Confidence is part of the data model, not metadata attached to it. Once meaning
can be retrofitted by a model, declared and inferred semantics must never be
indistinguishable: a pipeline that cannot mark its own output is worse than no
pipeline.

Nothing here is a general resolver. The judgement is a lookup in an import
table plus an optional hop through another module's exports.
"""

from __future__ import annotations

from typing import Any

from awl.ids import mint

__all__ = ["resolve"]

EXTRACTED = "EXTRACTED"
INFERRED = "INFERRED"
AMBIGUOUS = "AMBIGUOUS"

#: Decorators that give one name several definitions. Telling them apart needs
#: a disambiguator scheme; until one exists, picking the first would be a
#: fabricated identity.
_OVERLOAD_MARKERS = ("overload", "singledispatch", "register", "dispatch")


def _is_overloaded(declarations: list[dict[str, Any]], name: str) -> bool:
    """Return whether *name* has several definitions, or one marked overloaded."""
    matching = [entry for entry in declarations if entry.get("name") == name]
    if len(matching) > 1:
        return True
    return any(
        any(marker in decorator for marker in _OVERLOAD_MARKERS)
        for entry in matching
        for decorator in entry.get("decorators", [])
    )


def _re_export_origin(index: dict[str, Any], module: str, name: str) -> str | None:
    """Return where *module* got *name* from, if it re-exported it.

    Parameters
    ----------
    index : dict
        Module path to that module's ``SymbolFacts``.
    module, name : str
        The module named at the import site, and the name imported from it.

    Returns
    -------
    str or None
        The origin module, or None when the name is defined there or unknown.
    """
    facts = index.get(module)
    if facts is None:
        return None
    for export in facts.get("exports", []):
        if export.get("exportedName") == name:
            return export.get("fromModule") or None
    return None


def _bind_import(
    imported: dict[str, Any],
    index: dict[str, Any],
    scheme: str,
) -> tuple[dict[str, Any], str]:
    """Bind a name reached through an import, following one re-export hop."""
    module = imported["fromModule"]
    symbol = imported["importedName"]

    origin = _re_export_origin(index, module, symbol)
    if origin is not None:
        identity = mint(scheme=scheme, module=origin, symbol=symbol)
        # Kythe's aliases and aliases/root pair: keep the hop as written and
        # the resolved target, so a query picks its own indirection level.
        # Without both, pkg.Thing and pkg.impl.Thing become two nodes for one
        # entity, which is the likeliest duplicate source in Python.
        identity["aliasOf"] = module
        identity["aliasRoot"] = identity["iri"]
        return identity, INFERRED

    identity = mint(scheme=scheme, module=module, symbol=symbol)
    if imported.get("isAlias"):
        identity["aliasOf"] = imported["localName"]
        identity["aliasRoot"] = identity["iri"]
    return identity, EXTRACTED


def resolve(
    facts: dict[str, Any],
    *,
    index: dict[str, Any] | None = None,
    scheme: str = "py",
) -> dict[str, Any]:
    """Bind each use to an identity with a confidence tier.

    Parameters
    ----------
    facts : dict
        A ``SymbolFacts`` document.
    index : dict, optional
        Module path to that module's ``SymbolFacts``. Supplying it lets a
        re-export be followed one hop, which is a deduction and is therefore
        marked ``INFERRED``. Without it, resolution is per file and an import
        binds to the module named at the import site, which is what the source
        literally says.
    scheme : str, optional
        Language dimension passed through to minting.

    Returns
    -------
    dict
        Conforms to ``resolved-names.schema.json``. A binding with no identity
        is ``AMBIGUOUS``, never a fabricated identity: a wrong identity merges
        two entities, which is worse than admitting ignorance.
    """
    index = index or {}
    imports = facts.get("imports", [])
    by_name = {entry["localName"]: entry for entry in imports}
    declarations = facts.get("declarations", [])
    declared = {entry.get("name") for entry in declarations}
    has_star = any(entry.get("isStar") for entry in imports)
    module = facts.get("module", "")

    bindings = []
    for use in facts.get("uses", []):
        name = use["localName"]
        identity: dict[str, Any] | None = None

        if _is_overloaded(declarations, name):
            confidence = AMBIGUOUS
        elif name in by_name:
            identity, confidence = _bind_import(by_name[name], index, scheme)
        elif name in declared:
            identity = mint(scheme=scheme, module=module, symbol=name)
            confidence = EXTRACTED
        else:
            # Reached through a star import, or simply not in the scanned set.
            # Nothing in the surveyed prior art resolves a star import soundly,
            # so it stays flagged and the domain schema forbids it.
            confidence = AMBIGUOUS

        binding: dict[str, Any] = {
            "localName": name,
            "span": use["span"],
            "confidence": confidence,
        }
        if identity is not None:
            binding["identity"] = identity
        if confidence is AMBIGUOUS and has_star:
            binding["reason"] = "reached through a star import"
        bindings.append(binding)

    return {"file": facts["file"], "bindings": bindings}
