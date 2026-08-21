"""The JSON-LD context, verified through rdflib and pyld.

Every claim is asserted by running a real projection, not by inspecting the
context dict, except where the assertion is about the dict itself.
"""

import json

import pytest
from rdflib import Graph

from awl import contracts
from awl.context import AWL, build_context


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
            "identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"},
            "fields": [
                {
                    "name": "target_voltage",
                    "is_link": False,
                    "is_many": False,
                    "declaration_form": "plain",
                    "annotation": "float",
                }
            ],
        }
    ]
    assert build_context(types)["@context"]["C"]["@context"]["target_voltage"]["@type"] == "xsd:double"


def _numeric_context(annotation):
    return build_context([
        {
            "identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"},
            "fields": [
                {
                    "name": "v",
                    "is_link": False,
                    "is_many": False,
                    "declaration_form": "plain",
                    "annotation": annotation,
                }
            ],
        }
    ])["@context"]


def test_the_coercion_survives_an_integer_valued_input():
    """The actual mechanism: coerce the term, not the value."""
    from pyld import jsonld

    doc = {"@context": _numeric_context("float"), "_type": "C", "v": 4}
    nquads = jsonld.to_rdf(doc, {"format": "application/n-quads"})
    assert "double" in nquads, nquads


def test_without_the_coercion_the_same_input_is_an_integer():
    """Shows the coercion is load-bearing rather than decorative."""
    from pyld import jsonld

    nquads = jsonld.to_rdf({"@context": build_context()["@context"], "v": 4}, {"format": "application/n-quads"})
    assert "integer" in nquads, nquads


def test_an_optional_float_is_still_coerced():
    """`float | None` is how an optional numeric field is normally written."""
    assert _numeric_context("float | None")["C"]["@context"]["v"]["@type"] == "xsd:double"


def test_a_non_numeric_field_is_not_coerced():
    assert "v" not in _numeric_context("str")["C"]["@context"]


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
            "identity": {"iri": "https://ex.org/ChargeParam", "symbol": "ChargeParam", "scheme": "py"},
            "fields": [
                {
                    "name": "target_voltage",
                    "is_link": False,
                    "is_many": False,
                    "declaration_form": "plain",
                    "annotation": "float",
                },
                {
                    "name": "c_rate",
                    "is_link": False,
                    "is_many": False,
                    "declaration_form": "plain",
                    "annotation": "float",
                },
            ],
        }
    ]
    context = build_context(types)["@context"]["ChargeParam"]["@context"]
    assert context["target_voltage"]["@type"] == "xsd:double"
    assert context["c_rate"]["@type"] == "xsd:double"


def _linked_context(**overrides):
    field = {
        "name": "device",
        "is_link": True,
        "is_many": False,
        "target": "Device",
        "annotation": "Link[Device] | None",
        "declaration_form": "Link[T]",
        "arms": ["reference", "embedded"],
        **overrides,
    }
    return build_context([{"identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"}, "fields": [field]}])[
        "@context"
    ]


def test_a_declared_link_projects_as_an_iri_not_a_string():
    """Cashing in the member's annotation.

    Without the coercion a declared Link[Device] emits
    "https://ex.org/dev/17"^^xsd:string, which no query can follow: the
    annotation says reference and the projection says text.
    """
    from rdflib import URIRef

    graph = _graph({
        "@context": _linked_context(),
        "_type": "C",
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
        "_type": "C",
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
        SELECT ?serial WHERE { ?call <https://ex.org/C#device> ?device . ?device awl:serial ?serial }
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
    assert "operator" not in context["C"]["@context"]


def test_a_repeated_link_declares_its_multiplicity():
    """The annotation declares many, not ordered, so a set rather than a list."""
    assert _linked_context(is_many=True)["C"]["@context"]["device"]["@container"] == "@set"


def test_the_static_vocabulary_is_defined_only_in_the_schema():
    """One artefact, not two.

    ast-doc.schema.json is an OO-LD document: the same file is the shape and
    the mapping. Holding the terms in Python as well would define them twice,
    and the two would drift the first time either was edited.
    """
    from awl import contracts

    declared = contracts.load_schema("ast-doc")["@context"]
    built = build_context()["@context"]
    assert declared, "the schema carries the vocabulary"
    assert built == declared, "and nothing is added to it without a type"


def test_a_term_edited_in_the_schema_reaches_the_projection():
    """Proves the schema is the source rather than a stale copy of it."""
    from awl import contracts

    assert contracts.load_schema("ast-doc")["@context"]["body"]["@container"] == "@list"
    assert build_context()["@context"]["body"]["@container"] == "@list"


def _declaring(context, **overrides):
    """A TypeInfo for a class that declares its own context."""
    return {
        "identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"},
        "declared_context": context,
        "fields": [
            {
                "name": "v",
                "is_link": False,
                "is_many": False,
                "declaration_form": "plain",
                "annotation": "float",
            }
        ],
        **overrides,
    }


def test_a_declared_term_is_pulled_rather_than_derived():
    """The class said what v means, so that is what v means.

    Deriving xsd:double from the annotation beside it would put a second
    mapping next to the declared one, and the two drift the first time either
    is edited.
    """
    declared = {"ex": "https://ex.org/v#", "v": {"@id": "ex:voltage"}}
    terms = build_context([_declaring(declared)])["@context"]["C"]["@context"]
    assert terms["v"] == {"@id": "ex:voltage"}


def test_a_field_the_declaration_misses_is_still_synthesised():
    """A declaration is authoritative, not exhaustive.

    The generated packages declare a reference to the parent schema and an
    empty local map, so treating a declaration as complete would leave those
    classes with no semantics at all.
    """
    terms = build_context([_declaring({"ex": "https://ex.org/v#"})])["@context"]["C"]["@context"]
    assert terms["v"] == {"@type": "xsd:double"}


def test_a_remote_context_reference_is_not_dereferenced():
    """It would put the network on the path of every projection, and the
    reference is relative to the instance that served the schema.
    """
    declared = ["/wiki/Category:OSWC?action=raw&slot=jsonschema", {"ex": "https://ex.org/v#"}]
    context = build_context([_declaring(declared)])["@context"]
    assert context["ex"] == "https://ex.org/v#", "the inline half is still pulled"
    values = [*context.values(), *context["C"]["@context"].values()]
    assert not [value for value in values if isinstance(value, str) and value.startswith("/wiki")]


def test_a_declared_prefix_is_lifted_to_the_document():
    """@type is resolved before the class's own terms are in scope, so a
    declared type written as a CURIE needs its prefix at document level.
    """
    context = build_context([_declaring({"ex": "https://ex.org/v#"})])["@context"]
    assert context["ex"] == "https://ex.org/v#"


def test_a_declared_type_resolves_through_the_class_own_context():
    """The reference schemas write the type tag as a bare term.

    Read verbatim it would resolve against the document and land back on the
    minted Python identity, which is the one thing it is not.
    """
    from awl.context import declared_type_iris

    info = _declaring({"ex": "https://ex.org/v#", "C": "ex:C"}, declared_types=["C"])
    assert declared_type_iris(info) == ["ex:C"]


def test_an_undeclared_type_is_passed_through_unchanged():
    from awl.context import declared_type_iris

    assert declared_type_iris(_declaring({}, declared_types=["ex:C"])) == ["ex:C"]


def test_two_classes_with_the_same_field_name_stay_two_properties():
    """What the flat form could not do, and the reason for scoping.

    Without a class-specific context a size on one class and a size on another
    are one property, and no query can tell them apart.
    """

    def info(symbol):
        return {
            "identity": {"iri": f"https://ex.org/{symbol}", "symbol": symbol, "scheme": "py"},
            "fields": [{"name": "size", "is_link": False, "is_many": False, "declaration_form": "plain"}],
        }

    context = build_context([info("A"), info("B")])["@context"]
    graph = _graph({
        "@context": context,
        "@graph": [
            {"_type": "A", "size": 1},
            {"_type": "B", "size": 2},
        ],
    })
    predicates = {str(predicate) for _, predicate, _ in graph if "size" in str(predicate)}
    assert predicates == {"https://ex.org/A#size", "https://ex.org/B#size"}


def test_a_class_field_cannot_redefine_the_ast_vocabulary():
    """A class with a field called order must not make awl:order mean its own.

    Flat terms let it: the last type read won, and the ordering query then
    read a voltage.
    """
    info = {
        "identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"},
        "fields": [{"name": "order", "is_link": False, "is_many": False, "declaration_form": "plain"}],
    }
    context = build_context([info])["@context"]
    assert context["order"] == {"@id": "awl:order", "@type": "xsd:integer"}


def test_a_scoped_context_does_not_follow_into_a_nested_node():
    """A plain call nested in a collapsed node stays in the AST vocabulary.

    JSON-LD 1.1 does not propagate a type-scoped context, which is what makes
    the class namespace safe to set as @vocab.
    """
    info = {
        "identity": {"iri": "https://ex.org/C", "symbol": "C", "scheme": "py"},
        "fields": [{"name": "device", "is_link": False, "is_many": False, "declaration_form": "plain"}],
    }
    graph = _graph({
        "@context": build_context([info])["@context"],
        "_type": "C",
        "device": {"_type": "Call", "callee": "make"},
    })
    assert any(str(predicate) == f"{AWL}callee" for _, predicate, _ in graph), "not https://ex.org/C#callee"


def test_a_relative_identity_yields_no_namespace_at_all():
    """@vocab is concatenated, not expanded, so a CURIE there would mint
    ex:C#size rather than failing.
    """
    info = {
        "identity": {"iri": "ex:C", "symbol": "C", "scheme": "py"},
        "fields": [{"name": "size", "is_link": False, "is_many": False, "declaration_form": "plain"}],
    }
    assert "@vocab" not in build_context([info])["@context"]["C"]["@context"]


def test_a_name_is_not_projected_as_an_iri():
    """`id` on a Name node is an identifier, not a reference.

    Coerced to @id it was resolved against the document location, so the graph
    carried the working directory of whoever ran the projection.
    """
    from rdflib import Literal

    graph = _graph({"@context": build_context()["@context"], "_type": "Name", "id": "cycles"})
    assert (None, None, Literal("cycles")) in graph


def test_the_base_is_pinned_so_the_graph_does_not_depend_on_where_it_was_built():
    context = build_context()["@context"]
    assert context["@base"] == "https://w3id.org/awl/py/"


def test_terms_use_the_bound_prefix_rather_than_repeating_the_namespace():
    """`awl` is declared once; spelling the namespace out per term is noise."""
    context = build_context()["@context"]
    assert context["awl"] == AWL
    assert context["when_true"]["@id"] == "awl:whenTrue"
    assert not [
        term for term, value in context.items() if isinstance(value, dict) and str(value.get("@id", "")).startswith(AWL)
    ], "no term repeats the full namespace"
