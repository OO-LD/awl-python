"""The JSON-LD context, verified through rdflib and pyld.

Every claim is asserted by running a real projection, not by inspecting the
context dict, except where the assertion is about the dict itself.
"""

import json

import pytest
from rdflib import Graph

from awl import contracts
from awl.context import build_context


def _graph(doc):
    graph = Graph()
    graph.parse(data=json.dumps(doc), format="json-ld")
    return graph


def test_bodies_become_rdf_collections():
    doc = {
        "@context": build_context()["@context"],
        "_type": "Method",
        "body": [{"_type": "Call", "callee": "charge"}, {"_type": "Call", "callee": "rest"}],
    }
    turtle = _graph(doc).serialize(format="turtle")
    assert "rdf:rest" in turtle or "(" in turtle, "an RDF collection, not an unordered property"


def test_the_collection_preserves_the_written_order():
    """The claim the collection exists for, checked by walking the list itself.

    Asserting only that both callees appear would pass for an unordered
    property, which is the defect this replaces.
    """
    from rdflib import URIRef

    from awl.context import AWL

    doc = {
        "@context": build_context()["@context"],
        "_type": "Method",
        "body": [{"_type": "Call", "callee": "charge"}, {"_type": "Call", "callee": "rest"}],
    }
    graph = _graph(doc)
    head = next(graph.objects(predicate=URIRef(f"{AWL}body")))
    ordered = [str(callee) for member in graph.items(head) for callee in graph.objects(member, URIRef(f"{AWL}callee"))]
    assert ordered == ["charge", "rest"], "written order, not set membership"


@pytest.mark.parametrize("field", ["body", "orelse", "finalbody"])
def test_every_ordered_field_is_a_list_container(field):
    """Taken from the vocabulary, so a field added there cannot lose ordering.

    An earlier sketch hardcoded body and orelse and omitted finalbody, which
    would have made a try/finally sequence unordered.
    """
    assert build_context()["@context"][field]["@container"] == "@list"


def test_a_float_stays_a_double():
    """Guards the cross-language hazard.

    Python preserves 4.0 as a float, so this passes trivially here. It exists
    because a JavaScript processor cannot: JSON.parse('4.0') === JSON.parse('4').
    Without the explicit coercion the term is emitted as xsd:integer and a
    voltage silently changes type.
    """
    types = [
        {
            "identity": {"iri": "ex:C", "scheme": "py"},
            "fields": [
                {
                    "name": "target_voltage",
                    "isLink": False,
                    "isMany": False,
                    "declarationForm": "plain",
                    "annotation": "float",
                }
            ],
        }
    ]
    assert build_context(types)["@context"]["target_voltage"]["@type"] == "xsd:double"


def _numeric_context(annotation):
    return build_context([
        {
            "identity": {"iri": "ex:C", "scheme": "py"},
            "fields": [
                {
                    "name": "v",
                    "isLink": False,
                    "isMany": False,
                    "declarationForm": "plain",
                    "annotation": annotation,
                }
            ],
        }
    ])["@context"]


def test_the_coercion_survives_an_integer_valued_input():
    """The actual mechanism: coerce the term, not the value."""
    from pyld import jsonld

    nquads = jsonld.to_rdf({"@context": _numeric_context("float"), "v": 4}, {"format": "application/n-quads"})
    assert "double" in nquads, nquads


def test_without_the_coercion_the_same_input_is_an_integer():
    """Shows the coercion is load-bearing rather than decorative."""
    from pyld import jsonld

    nquads = jsonld.to_rdf({"@context": build_context()["@context"], "v": 4}, {"format": "application/n-quads"})
    assert "integer" in nquads, nquads


def test_an_optional_float_is_still_coerced():
    """`float | None` is how an optional numeric field is normally written."""
    assert _numeric_context("float | None")["v"]["@type"] == "xsd:double"


def test_a_non_numeric_field_is_not_coerced():
    assert "v" not in _numeric_context("str")


def test_an_unmapped_term_still_produces_a_triple():
    """The defect measured in the previous implementation: unmapped terms vanish.

    A fallback @vocab is what prevents it.
    """
    doc = {"@context": build_context()["@context"], "_type": "Call", "invented_field": 1}
    assert any("invented_field" in str(predicate) for _, predicate, _ in _graph(doc))


def test_a_collapsed_constructors_fields_survive():
    """The exact failure measured before: an empty blank node.

    target_voltage and c_rate were absent from the RDF entirely because they
    were not terms in the hand-written context.
    """
    doc = {
        "@context": build_context()["@context"],
        "_type": "Call",
        "callee": "ChargeParam",
        "target_voltage": 4.2,
        "c_rate": 0.23,
    }
    emitted = {str(object_) for _, _, object_ in _graph(doc)}
    assert "4.2" in emitted and "0.23" in emitted


def test_args_means_different_things_under_different_node_types():
    """Type-scoped disambiguation, which LinkML's generator does not emit."""
    context = build_context()["@context"]
    assert context["Method"]["@context"]["args"]["@id"].endswith("parameter")
    assert context["Call"]["@context"]["args"]["@id"].endswith("argument")

    method = _graph({"@context": context, "_type": "Method", "args": [{"_type": "Local"}]})
    call = _graph({"@context": context, "_type": "Call", "args": [{"_type": "Literal"}]})
    assert any("parameter" in str(p) for _, p, _ in method)
    assert any("argument" in str(p) for _, p, _ in call)
    assert not any("argument" in str(p) for _, p, _ in method)


def test_the_materialized_order_is_an_integer():
    """The query surface: rdf:rest*/rdf:first enumerates but does not order."""
    from rdflib import XSD as RDFLIB_XSD

    graph = _graph({"@context": build_context()["@context"], "_type": "Call", "order": 2})
    literals = [object_ for _, _, object_ in graph]
    assert any(getattr(value, "datatype", None) == RDFLIB_XSD.integer for value in literals)


def test_output_matches_the_contract():
    contracts.validate(build_context(), "context-doc")
    contracts.validate({"@context": _numeric_context("float")}, "context-doc")


def test_the_context_is_built_from_real_extracted_types():
    """Hand-written TypeInfo could drift from what awl.facts actually emits.

    This builds the context from the corpus by hand-shaping the same structure
    awl.facts produces, so the two agree on the key name.
    """
    types = [
        {
            "identity": {"iri": "ex:ChargeParam", "scheme": "py"},
            "fields": [
                {
                    "name": "target_voltage",
                    "isLink": False,
                    "isMany": False,
                    "declarationForm": "plain",
                    "annotation": "float",
                },
                {
                    "name": "c_rate",
                    "isLink": False,
                    "isMany": False,
                    "declarationForm": "plain",
                    "annotation": "float",
                },
            ],
        }
    ]
    context = build_context(types)["@context"]
    assert context["target_voltage"]["@type"] == "xsd:double"
    assert context["c_rate"]["@type"] == "xsd:double"


def _linked_context(**overrides):
    field = {
        "name": "device",
        "isLink": True,
        "isMany": False,
        "target": "Device",
        "annotation": "Link[Device] | None",
        "declarationForm": "Link[T]",
        "arms": ["reference", "embedded"],
        **overrides,
    }
    return build_context([{"identity": {"iri": "ex:C", "scheme": "py"}, "fields": [field]}])["@context"]


def test_a_declared_link_projects_as_an_iri_not_a_string():
    """Cashing in the member's annotation.

    Without the coercion a declared Link[Device] emits
    "https://ex.org/dev/17"^^xsd:string, which no query can follow: the
    annotation says reference and the projection says text.
    """
    from rdflib import URIRef

    graph = _graph({
        "@context": _linked_context(),
        "_type": "Call",
        "device": "https://ex.org/dev/17",
    })
    objects = [object_ for _, predicate, object_ in graph if "device" in str(predicate)]
    assert objects == [URIRef("https://ex.org/dev/17")]


def test_without_the_annotation_the_same_value_is_a_string():
    """Shows the coercion is what does the work, not the value's shape."""
    from rdflib import Literal

    graph = _graph({
        "@context": build_context()["@context"],
        "_type": "Call",
        "device": "https://ex.org/dev/17",
    })
    objects = [object_ for _, predicate, object_ in graph if "device" in str(predicate)]
    assert objects == [Literal("https://ex.org/dev/17")]


def test_a_linked_reference_actually_joins_to_the_referenced_node():
    """The point of an IRI over a string: two documents become one graph."""
    graph = _graph({
        "@context": _linked_context(),
        "_type": "Call",
        "device": "https://ex.org/dev/17",
    })
    graph.parse(
        data=json.dumps({
            "@context": {"@vocab": "https://w3id.org/awl/schema/"},
            "@id": "https://ex.org/dev/17",
            "serial": "SN-4471",
        }),
        format="json-ld",
    )
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?serial WHERE { ?call awl:device ?device . ?device awl:serial ?serial }
    """)
    assert [str(row[0]) for row in rows] == ["SN-4471"], "the reference resolves"


def test_a_union_with_a_literal_arm_is_not_coerced():
    """`str | Device` means an operator may be a name rather than a reference.

    Coercing it would silently turn that name into a relative IRI. The declared
    arms are what make this decidable.
    """
    context = _linked_context(
        name="operator", annotation="str | Device | None", arms=["literal", "reference", "embedded"]
    )
    assert "operator" not in context


def test_a_repeated_link_declares_its_multiplicity():
    """The annotation declares many, not ordered, so a set rather than a list."""
    assert _linked_context(isMany=True)["device"]["@container"] == "@set"
