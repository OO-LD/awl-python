"""Build the JSON-LD context that projects an AstDoc to correct RDF.

The cheapest lever in the design: it retargets the whole projection without
touching the walker. Most of the defects measured in the previous hand-written
context were context work, not walker work. On the running example that context
rendered a collapsed constructor as an empty blank node, because
``target_voltage`` and ``c_rate`` were not terms in it and JSON-LD drops
unmapped terms.
"""

from __future__ import annotations

from typing import Any

from awl.vocab import ORDERED_FIELDS

__all__ = ["AWL", "XSD", "build_context"]

AWL = "https://w3id.org/awl/schema/"
XSD = "http://www.w3.org/2001/XMLSchema#"

#: Annotations coerced to an explicit RDF datatype. Only float needs it: an
#: integer-valued float is otherwise emitted as xsd:integer.
_COERCIONS = {"float": "xsd:double"}

#: Terms whose meaning depends on the node type they appear under. `args` is a
#: parameter list under a method declaration and an argument list under a call.
#: A type-scoped context states that declaratively and per type, which is
#: stronger than a qualifier enum and is what LinkML's generator does not emit.
_TYPE_SCOPED = {
    "Method": {"args": {"@id": f"{AWL}parameter", "@container": "@list"}},
    "Call": {"args": {"@id": f"{AWL}argument", "@container": "@list"}},
}


def _coercion_for(annotation: str | None) -> str | None:
    """Return the RDF datatype for an annotation as written, or None.

    Handles a union arm, because ``float | None`` is the common way an
    optional numeric field is declared and it must still be coerced.
    """
    if not annotation:
        return None
    for arm in annotation.split("|"):
        coercion = _COERCIONS.get(arm.strip())
        if coercion:
            return coercion
    return None


def build_context(types: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the document-level context.

    Parameters
    ----------
    types : list of dict, optional
        ``TypeInfo`` documents. A field annotated ``float`` gets an explicit
        ``xsd:double`` coercion.

    Returns
    -------
    dict
        Conforms to ``context-doc.schema.json``.

    Notes
    -----
    Ordered statement lists get ``@container: @list``, which JSON-LD 1.1 API
    section 8.3 defines as producing an RDF collection. That yields members
    rather than positions: recovering an index means counting ``rdf:rest``
    hops, and SPARQL 1.1 property paths have only ``*``, ``+`` and ``?``. So
    ``order`` is emitted as a materialized integer alongside, and it is the
    query surface.

    Two alternatives are ruled out rather than overlooked. JSON-LD index maps
    are defined for keys that have "no semantic meaning", which disqualifies
    them by the specification's own framing, and SHACL ``sh:order`` is
    non-validating form-layout metadata.

    The numeric coercion guards a **cross-language** hazard. Python preserves
    ``4.0`` as a float, so it costs nothing here; JavaScript cannot, since
    ``JSON.parse('4.0') === JSON.parse('4')``. Without the coercion a voltage
    written ``4.0`` silently becomes an integer on the way through a
    JavaScript processor.
    """
    context: dict[str, Any] = {
        "awl": AWL,
        "xsd": XSD,
        # A fallback vocabulary, so an unmapped term still produces a triple
        # instead of being dropped.
        "@vocab": AWL,
        "_type": "@type",
        "order": {"@id": f"{AWL}order", "@type": "xsd:integer"},
        "argumentIndex": {"@id": f"{AWL}argumentIndex", "@type": "xsd:integer"},
        "iteration": {"@id": f"{AWL}iteration", "@type": "xsd:integer"},
    }
    # Taken from the vocabulary rather than restated, so a field added there
    # cannot silently lose its ordering here.
    for field in ORDERED_FIELDS:
        context[field] = {"@id": f"{AWL}{field}", "@container": "@list"}

    for node_type, terms in _TYPE_SCOPED.items():
        context[node_type] = {"@id": f"{AWL}{node_type}", "@context": terms}

    for info in types or []:
        for field in info.get("fields", []):
            coercion = _coercion_for(field.get("annotation"))
            if coercion:
                context[field["name"]] = {"@id": f"{AWL}{field['name']}", "@type": coercion}
    return {"@context": context}
