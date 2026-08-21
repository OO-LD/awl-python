"""Project a document to RDF, and read it back where that is honestly possible.

Export attaches a context and materializes schema-declared instance types, per
the OO-LD rule that tooling exporting an instance must do so: a JSON-LD-only
consumer sees the instance and its context but never the schema.

Import is scoped, and the scope is a refusal. The reduced profiles elide by
construction, so no importer can recover what was dropped, and a silent partial
reconstruction is worse than an error because the caller cannot tell which one
they received.

A triple carries no attributes, so a confidence tier cannot ride on an edge.
Named graphs carry it instead. That is not optional once meaning can be
retrofitted by a model: a pipeline that cannot mark its own output is worse
than no pipeline.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["CONFIDENCE_GRAPHS", "from_graph", "to_dataset", "to_graph", "to_jsonld"]

#: Profiles that drop nodes, and therefore cannot be read back.
LOSSY_PROFILES = frozenset({"workflow", "provenance", "signature"})

#: One named graph per confidence tier, so retrofitted meaning stays
#: distinguishable from declared meaning.
CONFIDENCE_GRAPHS = {
    "EXTRACTED": "https://w3id.org/awl/graph/extracted",
    "INFERRED": "https://w3id.org/awl/graph/inferred",
    "AMBIGUOUS": "https://w3id.org/awl/graph/ambiguous",
}


def to_jsonld(doc: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach a context to a document.

    Parameters
    ----------
    doc : dict
        An ``AstDoc``, possibly containing collapsed nodes.
    context : dict, optional
        A ``ContextDoc``. Built from the vocabulary alone when omitted.

    Returns
    -------
    dict
        A JSON-LD document. A collapsed node keeps its own embedded context,
        which is what maps its fields to the type's namespace rather than to
        this vocabulary.
    """
    from awl.context import build_context

    resolved = context or build_context()
    return {"@context": resolved["@context"], **doc}


def to_graph(doc: dict[str, Any], *, context: dict[str, Any] | None = None):
    """Return an rdflib Graph for *doc*.

    Parameters
    ----------
    doc : dict
        An ``AstDoc``.
    context : dict, optional
        A ``ContextDoc``.

    Returns
    -------
    rdflib.Graph
    """
    from rdflib import Graph

    graph = Graph()
    graph.parse(data=json.dumps(to_jsonld(doc, context=context)), format="json-ld")
    return graph


def to_dataset(
    doc: dict[str, Any],
    *,
    confidence: str = "EXTRACTED",
    context: dict[str, Any] | None = None,
):
    """Return an rdflib Dataset with the statements in a tier-named graph.

    Parameters
    ----------
    doc : dict
        An ``AstDoc``.
    confidence : str
        One of the keys of :data:`CONFIDENCE_GRAPHS`.
    context : dict, optional
        A ``ContextDoc``.

    Returns
    -------
    rdflib.Dataset

    Raises
    ------
    KeyError
        If the tier is unknown, rather than silently defaulting to
        ``EXTRACTED``, which would make retrofitted meaning look declared.
    """
    from rdflib import Dataset, URIRef

    name = CONFIDENCE_GRAPHS[confidence]
    dataset = Dataset()
    graph = dataset.graph(URIRef(name))
    graph.parse(data=json.dumps(to_jsonld(doc, context=context)), format="json-ld")
    return dataset


def from_graph(graph, *, profile: str = "ast") -> Any:
    """Reconstruct a document from RDF.

    Parameters
    ----------
    graph : rdflib.Graph
    profile : str
        The profile the graph was produced at.

    Returns
    -------
    Any
        The expanded JSON-LD form.

    Raises
    ------
    ValueError
        If *profile* elides, because the dropped nodes are unrecoverable and a
        partial reconstruction would be indistinguishable from a complete one.

    Notes
    -----
    Two preconditions for a faithful round trip are met and two are not.
    Ordering survives, verified: ``@container: @list`` produces an
    ``rdf:List``. Unmapped keys survive, verified: an embedded ``@vocab`` keeps
    them. Numeric fidelity on the way back is **not** verified, and precision
    loss was measured in the other direction. Recovering the exact tree shape
    needs JSON-LD framing, which is **not implemented here**.

    So this returns the expanded form, not a document identical to the input.
    The authoritative round trip remains document to source, never RDF to
    source.
    """
    if profile in LOSSY_PROFILES:
        raise ValueError(
            f"profile {profile!r} elides by construction, so RDF cannot be read back; "
            "only the 'ast' profile round-trips"
        )
    from pyld import jsonld

    # Serialized as n-triples, not n-quads: rdflib refuses n-quads for a store
    # that is not context-aware, and n-triples is a subset of the n-quads
    # grammar, so the parser on the other side accepts it unchanged.
    return jsonld.from_rdf(graph.serialize(format="nt"), {"useNativeTypes": True})
