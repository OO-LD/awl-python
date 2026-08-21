"""The single identity-minting authority for AWL-LD.

Every producer must route through here. Two producers that mint differently
split one entity into disconnected nodes, and because these are global IRIs
the result is a wrong assertion about the world rather than a local
inconsistency in one tool's database.

The three producers are the AST walk, the collapse and the RDF projection.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

__all__ = [
    "DEFAULT_BASE",
    "class_identity",
    "mint",
    "mint_instantiation",
    "normalize",
]

DEFAULT_BASE = "https://w3id.org/awl/"

_NON_WORD = re.compile(r"[^\w.]+", re.UNICODE)
_RUNS = re.compile(r"_+")


def normalize(text: str) -> str:
    """Normalize one identifier segment, preserving case.

    Parameters
    ----------
    text : str
        A module path, symbol path or type name.

    Returns
    -------
    str
        NFKC-normalized, with runs of non-identifier characters collapsed to a
        single underscore and leading and trailing underscores removed. Dots
        are kept, because they separate the segments of a dotted path.

    Notes
    -----
    Guarantees, enforced by tests:

    - idempotent: ``normalize(normalize(s)) == normalize(s)``
    - case-preserving: distinct casings stay distinct identities

    **Do not casefold.** ``graphify/ids.py`` does, and copying that recipe here
    would be a correctness bug rather than a style choice. It casefolds so its
    LLM-produced and AST-produced ids reconcile despite punctuation and casing
    drift. AWL-LD has no probabilistic producer in this path, and Python is
    case-sensitive, so casefolding *merges genuinely different symbols*:

    ============================  ==================  =========
    Input pair                    Casefolded          Preserved
    ============================  ==================  =========
    ``battery.Params``            ``battery.params``  distinct
    ``battery.params``            ``battery.params``  distinct
    ``ChargeParam``               ``chargeparam``     distinct
    ``chargeParam``               ``chargeparam``     distinct
    ============================  ==================  =========

    That is the ghost-node failure inverted: false merging instead of false
    splitting, and a merge is the harder one to notice, because the graph
    simply contains one node where it should contain two.
    """
    current = unicodedata.normalize("NFKC", text)
    current = _NON_WORD.sub("_", current)
    return _RUNS.sub("_", current).strip("_")


def mint(
    *,
    scheme: str,
    module: str = "",
    symbol: str = "",
    version: str | None = None,
    disambiguator: str | None = None,
    base: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Mint an identity.

    Parameters
    ----------
    scheme : str
        Language or frontend dimension, e.g. ``"py"``.
    module : str, optional
        Dotted module path, e.g. ``"battery.params"``.
    symbol : str, optional
        Dotted path within the module, e.g. ``"ChargeParam.charge"``.
    version : str or None, optional
        Set for OO-LD classes and for distributions whose metadata is
        inspectable. Left empty rather than guessed.
    disambiguator : str or None, optional
        Distinguishes overloads and typed instantiations.
    base : str, optional
        Namespace prefix. A single default for now; the Kythe ``vnames.json``
        style path-pattern configuration arrives when a second corpus needs a
        different namespace, not before.

    Returns
    -------
    dict
        Conforms to ``identity.schema.json``. Only ``iri`` should be compared
        by consumers; the other fields are provenance for humans.
    """
    # Module and symbol join with "/" and not ".", or a.b::C and a::b.C
    # flatten to the same string. See test_module_and_symbol_boundaries_survive.
    parts = [part for part in (normalize(module), normalize(symbol)) if part]
    iri = "/".join([f"{base}{scheme}", *parts])
    if version:
        iri = f"{iri}@{version}"
    if disambiguator:
        iri = f"{iri}#{disambiguator}"
    return {
        "iri": iri,
        "scheme": scheme,
        "module": module,
        "symbol": symbol,
        "version": version,
        "disambiguator": disambiguator,
        "aliasOf": None,
        "aliasRoot": None,
    }


def mint_instantiation(callee: dict[str, Any], arg_types: list[str]) -> dict[str, Any]:
    """Mint the identity of a *typed instantiation* of a generic callee.

    Parameters
    ----------
    callee : dict
        An identity previously returned by :func:`mint`.
    arg_types : list of str
        Argument type names, in positional order.

    Returns
    -------
    dict
        An identity whose IRI extends the callee's with a disambiguator, so a
        consumer that only knows the generic form still matches by prefix.

    Notes
    -----
    A bare function name carries no semantics and never will::

        scipy.stats.linregress                        no semantics, ever
        scipy.stats.linregress(LinearStrain, Stress)  -> ModulusOfElasticity

    Attaching a range to the bare name asserts it for every use of linregress
    on earth. The semantics belong to the instantiation, which is what SCIP's
    ``method-disambiguator`` and Kythe's opaque ``signature`` field exist for.
    With types on the arguments the instantiation is derivable statically at
    every call site, so a model is needed once to propose the mapping and
    dispatch afterwards is deterministic.
    """
    disambiguator = "(" + ",".join(normalize(name) for name in arg_types) + ")"
    return mint(
        scheme=callee["scheme"],
        module=callee.get("module", ""),
        symbol=callee.get("symbol", ""),
        version=callee.get("version"),
        disambiguator=disambiguator,
    )


def class_identity(
    *,
    scheme: str,
    module: str,
    symbol: str,
    instance_rdf_types: list[str] | None = None,
    type_field_default: list[str] | str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Mint a class identity, following the OO-LD precedence.

    Parameters
    ----------
    scheme, module, symbol : str
        As for :func:`mint`.
    instance_rdf_types : list of str or None, optional
        The schema's ``x-oold-instance-rdf-type``. A list, because it co-types.
    type_field_default : list of str or str or None, optional
        The inline ``type`` field default, e.g. ``"ex:Person"`` or
        ``["Diameter"]``. Consulted only when the schema declares nothing.
    version : str or None, optional
        From ``x-oold-version`` or a versioned ``$id``.

    Returns
    -------
    dict
        An identity carrying an extra ``declaredTypes`` list.

    Notes
    -----
    Precedence, verified against the OO-LD spec section on schema instances:
    ``x-oold-instance-rdf-type`` wins, then the inline ``type`` field default,
    then the import path. Under ``allOf`` the nearest declaration replaces a
    base class's value rather than appending (rule OOLD-INS-559f), so the
    caller passes the already-resolved list. Mirrors ``get_cls_iri()`` so
    AWL-LD and oold cannot disagree.
    """
    declared = list(instance_rdf_types or [])
    if not declared and type_field_default:
        declared = [type_field_default] if isinstance(type_field_default, str) else list(type_field_default)
    identity = mint(scheme=scheme, module=module, symbol=symbol, version=version)
    # The minted IRI stays authoritative and resolvable. A declared type is
    # usually a CURIE ("ex:ChargeParam") against a prefix this package does not
    # control; overwriting `iri` with it produced predicates like
    # `ex:ChargeParam#target_voltage`, which rdflib accepts and which join with
    # nothing. Declared types are carried alongside, never instead.
    identity["declaredTypes"] = declared
    return identity
