"""Build the JSON-LD context that projects an AstDoc to correct RDF.

The cheapest lever in the design: it retargets the whole projection without
touching the walker. Most of the defects measured in the previous hand-written
context were context work, not walker work. On the running example that context
rendered a collapsed constructor as an empty blank node, because
``target_voltage`` and ``c_rate`` were not terms in it and JSON-LD drops
unmapped terms.

Two halves, and they are built differently on purpose.

The **static** half is the AST vocabulary. It is not written here at all: it
lives in ``ast-doc.schema.json``, which is one file that is both the shape and
the mapping, so the terms are defined once. Its property names are chosen
(``when_true`` reads as ``awl:whenTrue``), which is precisely what ``@vocab``
cannot derive, so each carries an ``@id``.

The **dynamic** half is one term per class, scoped to itself. A class's field
names are the author's, carried verbatim, so ``@vocab`` yields exactly the
right IRI and a field that needs no coercion costs no term at all. Where the
class declares its own context, that is pulled rather than derived.
"""

from __future__ import annotations

from typing import Any

__all__ = ["AWL", "PY", "XSD", "build_context", "declared_prefixes", "declared_type_iris", "type_terms"]

AWL = "https://w3id.org/awl/schema/"
PY = "https://w3id.org/awl/py/"
XSD = "http://www.w3.org/2001/XMLSchema#"

#: Annotations coerced to an explicit RDF datatype. Only float needs it: an
#: integer-valued float is otherwise emitted as xsd:integer.
_COERCIONS = {"float": "xsd:double"}


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
    # The static half of the vocabulary lives in ast-doc.schema.json, which is
    # an OO-LD document: one file that is both the shape and the mapping.
    # Holding it here as well would define the same terms twice, and the two
    # would drift the first time either was edited.
    from awl import contracts

    context: dict[str, Any] = dict(contracts.load_schema("ast-doc")["@context"])

    for info in types or []:
        _add_type(context, info)
    return {"@context": context}


def _curie(iri: str) -> str:
    """Return *iri* against a bound prefix where one applies."""
    for prefix, namespace in (("py", PY), ("awl", AWL), ("xsd", XSD)):
        if iri.startswith(namespace):
            return f"{prefix}:{iri[len(namespace) :]}"
    return iri


def _add_type(context: dict[str, Any], info: dict[str, Any]) -> None:
    """Add one declared class to the context, as a term scoped to itself.

    Naming the class as a term is what lets a collapsed node be written
    ``{"@type": "ChargeParam", ...}`` rather than carrying an IRI and a
    separate copy of the local name. The term resolves to the minted IRI, so
    the compact form and the RDF agree without repeating anything.

    Its fields hang off that term rather than off the document, because a
    field name is only meaningful under the class that declares it. Flat terms
    made two classes with a ``size`` field one property, and let a class with a
    field called ``body`` or ``order`` silently redefine the AST spine.
    """
    identity = (info.get("identity") or {}).get("iri")
    name = (info.get("identity") or {}).get("symbol")
    if not identity or not name:
        return
    for prefix, namespace in declared_prefixes(info).items():
        # A prefix binds a namespace rather than carrying a meaning, so it
        # belongs to the document. It has to: a declared type is written as a
        # CURIE beside the class name, and @type is resolved before the class's
        # own terms are in scope. Left scoped, ex:ChargeParam would stay an
        # opaque IRI with a made-up ex scheme.
        context.setdefault(prefix, namespace)
    context[name] = {"@id": _curie(identity), "@context": type_terms(info)}


def declared_prefixes(info: dict[str, Any]) -> dict[str, str]:
    """Return the prefix bindings a class declares.

    A term whose value is a plain string ending in a delimiter is a namespace,
    which is the same rule JSON-LD 1.1 uses to decide whether a term may be
    used as a prefix.
    """
    return {
        term: value
        for term, value in _declared_terms(info.get("declared_context")).items()
        if isinstance(value, str) and value[-1:] in ("#", "/", ":")
    }


def declared_type_iris(info: dict[str, Any]) -> list[str]:
    """Return the instance types a class declares, as the class means them.

    The reference schemas write the type tag as a bare term and let the class's
    own context say what it resolves to: ``type`` defaults to
    ``["QuantityValue"]`` and the context maps ``QuantityValue`` to
    ``qudt:QuantityValue``. Read verbatim, that term would resolve against the
    document instead and land back on the minted Python identity, which is the
    one thing it is not: the class named an ontology class, and saying so is
    the whole point of declaring it.

    The minted identity is not replaced by it. Both are true of the instance
    and the graph carries both, because every other producer, from member
    writes to the def-use graph, joins on the minted one.
    """
    declared = _declared_terms(info.get("declared_context"))
    resolved = []
    for name in info.get("declared_types") or []:
        term = declared.get(name)
        if isinstance(term, dict):
            term = term.get("@id")
        resolved.append(term if isinstance(term, str) else name)
    return resolved


def type_terms(info: dict[str, Any]) -> dict[str, Any]:
    """Return the terms that hold inside a node of this type.

    Parameters
    ----------
    info : dict
        A ``TypeInfo``.

    Returns
    -------
    dict
        A JSON-LD context. Used both here, scoped under the class term, and by
        awl.collapse for the context it embeds in a standalone node, so the two
        cannot name one property two ways.

    Notes
    -----
    The class namespace arrives as ``@vocab`` rather than as one term per
    field, so a field that needs no coercion costs nothing at all. What is
    left is only what ``@vocab`` cannot express: a declared term, a datatype,
    or a reference.

    A type-scoped context does not propagate to nested node objects (JSON-LD
    1.1, 4.1.9), which is what keeps a plain ``Call`` nested inside a collapsed
    node in the AST vocabulary instead of dragging it into the class namespace.
    """
    symbol = (info.get("identity") or {}).get("symbol")
    identity = (info.get("identity") or {}).get("iri") or ""
    # A relative IRI in @vocab is not expanded, it is concatenated as written,
    # so a declared CURIE such as ex:ChargeParam would mint ex:ChargeParam#size
    # rather than failing. Better no namespace than a fabricated one.
    terms: dict[str, Any] = {"@vocab": f"{identity}#"} if "://" in identity else {}
    declared = _declared_terms(info.get("declared_context"))
    # The class term and its prefixes are the document's business, not this
    # node's: what a class is called cannot be settled from inside a node that
    # is already known to be one. See _add_type and declared_type_iris.
    prefixes = declared_prefixes(info)
    terms.update({term: value for term, value in declared.items() if term != symbol and term not in prefixes})

    for field in info.get("fields", []):
        if field["name"] in terms:
            continue
        term = _term_for(field)
        if term is not None:
            terms[field["name"]] = term
    return terms


def _declared_terms(declared: Any) -> dict[str, Any]:
    """Return the terms a class declares for itself.

    A declared context is **pulled, not generated**: where the class has said
    what a field means, that is the answer, and deriving a second mapping
    beside it from the annotation is how the two drift apart.

    It is not the whole answer, though, which is why synthesis still fills the
    gaps. The generated OpenSemanticLab packages declare
    ``["<parent schema>", {}]``: every term they own is behind a reference to
    the schema that declares it. Treating a declaration as exhaustive would
    leave those classes with no semantics at all.

    Notes
    -----
    A string entry is a remote context reference and is skipped. Dereferencing
    it would put the network on the path of every projection, and the reference
    is usually relative to the instance that served the schema, which is not
    recoverable from the Python source. Resolving one is schema-side work that
    oold-python will do; this package will consume it rather than growing a
    second resolver beside it.
    """
    if declared is None:
        return {}
    entries = declared if isinstance(declared, list) else [declared]
    terms: dict[str, Any] = {}
    for entry in entries:
        if isinstance(entry, dict):
            terms.update(entry)
    return terms


def _term_for(field: dict[str, Any]) -> dict[str, Any] | None:
    """Return the context term a declared field needs, or None.

    This is where a member's annotation is cashed in. Two coercions come out
    of it, and both are the difference between a graph that joins and one that
    only looks like it does.

    A link field is coerced to ``@id``, so its value becomes an IRI rather
    than a string. Without it a declared ``Link[Device]`` projects as
    ``"https://ex.org/dev/17"^^xsd:string``, which no query can follow: the
    annotation says the field is a reference and the projection says it is
    text.

    A link whose union admits a literal arm is **not** coerced. ``str | Device``
    means an operator may legitimately be a name rather than a reference, and
    coercing it would silently turn that name into a relative IRI. The declared
    arms are what make this decidable, which is the reason to record them.

    Neither term carries an ``@id``. The property IRI is the class namespace
    plus the field name, which is exactly what the surrounding ``@vocab``
    yields, so spelling it out would only be a second place to keep it right.
    """
    if field.get("is_link") and "literal" not in (field.get("arms") or []):
        term: dict[str, Any] = {"@type": "@id"}
        if field.get("is_many"):
            # A set, not a list: the annotation declares multiplicity, not order.
            term["@container"] = "@set"
        return term

    coercion = _coercion_for(field.get("annotation"))
    if coercion:
        return {"@type": coercion}
    return None
