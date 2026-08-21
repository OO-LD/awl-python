"""The RDF projection, its confidence tiers, and its import refusal.

Imports only the module under test, awl.context and the contracts package.
"""

import pytest

from awl import contracts
from awl.rdf import CONFIDENCE_GRAPHS, from_graph, to_dataset, to_graph, to_jsonld

METHOD = {
    "_type": "Method",
    "body": [
        {"_type": "Call", "callee": "charge", "order": 0},
        {"_type": "Call", "callee": "rest", "order": 1},
    ],
}


def test_a_workflow_body_is_ordered_in_rdf():
    turtle = to_graph(METHOD).serialize(format="turtle")
    assert "rdf:rest" in turtle or "(" in turtle, "an RDF collection, not an unordered property"


def test_the_materialized_order_is_queryable_without_walking_the_list():
    """The reason both mechanisms are emitted.

    A collection preserves order but yields members, not positions: recovering
    an index means counting rdf:rest hops, and SPARQL property paths cannot
    count. The integer is what a query selects on.
    """
    graph = to_graph(METHOD)
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee ?order WHERE { ?step awl:callee ?callee ; awl:order ?order }
        ORDER BY ?order
    """)
    assert [(str(callee), int(order)) for callee, order in rows] == [("charge", 0), ("rest", 1)]


def test_which_step_precedes_another_is_answerable():
    """The concrete measure of success: a question about sequence, in SPARQL."""
    graph = to_graph(METHOD)
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?earlier WHERE {
          ?a awl:callee ?earlier ; awl:order ?i .
          ?b awl:callee "rest"  ; awl:order ?j .
          FILTER(?i < ?j)
        }
    """)
    assert [str(row[0]) for row in rows] == ["charge"]


def test_a_collapsed_node_keeps_its_own_context():
    """The document context must not override the type's embedded one."""
    doc = {
        "_type": "Method",
        "body": [
            {
                "@context": {"@vocab": "https://w3id.org/awl/py/battery.params/ChargeParam#"},
                "@type": "ex:ChargeParam",
                "_callee": "ChargeParam",
                "target_voltage": 4.2,
            }
        ],
    }
    predicates = {str(predicate) for _, predicate, _ in to_graph(doc)}
    assert any("ChargeParam#target_voltage" in predicate for predicate in predicates), predicates


def test_to_jsonld_leaves_the_document_untouched_apart_from_the_context():
    attached = to_jsonld({"_type": "Call", "callee": "charge"})
    assert attached["_type"] == "Call"
    assert attached["callee"] == "charge"
    assert "@context" in attached


@pytest.mark.parametrize("profile", ["workflow", "provenance", "signature"])
def test_reading_back_a_reduced_profile_is_refused(profile):
    """A partial reconstruction is worse than an error: the caller cannot tell
    which one they received.
    """
    graph = to_graph({"_type": "Module", "body": []})
    with pytest.raises(ValueError, match="elides"):
        from_graph(graph, profile=profile)


def test_the_ast_profile_can_be_read_back():
    restored = from_graph(to_graph({"_type": "Module", "body": [METHOD]}), profile="ast")
    assert restored, "the ast profile is the one that can be read back"


def test_reading_back_returns_the_expanded_form_not_the_original_document():
    """Stated rather than overclaimed.

    Framing, which is what would recover the exact tree shape, is not
    implemented. Calling this lossless would be the easiest place in the design
    to overclaim.
    """
    doc = {"_type": "Module", "body": [METHOD]}
    assert from_graph(to_graph(doc), profile="ast") != doc


def test_inferred_statements_land_in_a_separate_graph():
    """Retrofitted meaning must stay distinguishable from declared meaning."""
    dataset = to_dataset({"_type": "Call", "callee": "charge"}, confidence="INFERRED")
    populated = {str(context.identifier) for context in dataset.contexts() if len(context)}
    assert populated == {CONFIDENCE_GRAPHS["INFERRED"]}, populated


def test_the_three_tiers_get_three_distinct_graphs():
    assert len(set(CONFIDENCE_GRAPHS.values())) == 3


def test_extracted_and_inferred_statements_do_not_share_a_graph():
    """The property the tiers exist for, checked across two datasets."""
    extracted = to_dataset({"_type": "Call", "callee": "charge"}, confidence="EXTRACTED")
    inferred = to_dataset({"_type": "Call", "callee": "charge"}, confidence="INFERRED")
    names = {str(context.identifier) for context in extracted.contexts() if len(context)} | {
        str(context.identifier) for context in inferred.contexts() if len(context)
    }
    assert len(names) == 2


def test_an_unknown_tier_is_refused():
    """Rather than defaulting to EXTRACTED, which would make retrofitted
    meaning look declared.
    """
    with pytest.raises(KeyError):
        to_dataset({"_type": "Call"}, confidence="PROBABLY")


def test_a_float_survives_the_projection_as_a_double():
    """The cross-language hazard, carried through the real export path."""
    from awl.context import build_context

    types = [
        {
            "identity": {"iri": "ex:C", "scheme": "py"},
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
    graph = to_graph({"_type": "Call", "target_voltage": 4}, context=build_context(types))
    datatypes = {str(getattr(o, "datatype", "")) for _, _, o in graph}
    assert any("double" in datatype for datatype in datatypes), datatypes


def test_the_corpus_projects_without_error():
    """External validity: every fixture, not just the worked example."""
    import ast

    from ast2json import ast2json

    for path in contracts.corpus_files():
        graph = to_graph(ast2json(ast.parse(path.read_text(encoding="utf-8"))))
        assert len(graph) > 0, path
