"""The control-flow graph: steps connected by the reason control moves.

Imports only the module under test and the contracts package.
"""

import json

import pytest
from rdflib import Graph

from awl import contracts
from awl.controlflow import EDGE_KINDS, analyze, as_document

TIER2 = (contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py").read_text(encoding="utf-8")


def _cfg(source, module="m"):
    return analyze(source, module=module, file="sample.py")


def _labelled(graph):
    """Return edges as (label, kind, label) triples, for readable assertions."""
    by_id = {step["id"]: step for step in graph["steps"]}

    def label(step):
        return step["callee"] or step["condition"] or step["parser_type_name"]

    return {(label(by_id[edge["from"]]), edge["kind"], label(by_id[edge["to"]])) for edge in graph["edges"]}


def test_sequential_steps_are_connected_unconditionally():
    assert ("a", "next", "b") in _labelled(_cfg("a()\nb()\n"))


def test_a_conditional_emits_both_arms():
    """An ordered body says a step comes second; it cannot say "only if"."""
    edges = _labelled(_cfg("if flag:\n    a()\nelse:\n    b()\n"))
    assert ("flag", "when_true", "a") in edges
    assert ("flag", "when_false", "b") in edges


def test_falling_past_a_conditional_is_still_a_decision():
    """No else arm, so control skips the body. Emitting that as plain
    sequence would lose the fact that skipping was a decision.
    """
    edges = _labelled(_cfg("if flag:\n    a()\nb()\n"))
    assert ("flag", "when_true", "a") in edges
    assert ("flag", "when_false", "b") in edges


def test_a_loop_has_a_back_edge():
    """What makes a loop a loop rather than a list."""
    edges = _labelled(_cfg("while cond:\n    a()\n"))
    assert ("cond", "when_true", "a") in edges
    assert ("a", "repeat", "cond") in edges


def test_a_for_loop_says_which_edge_is_an_iteration():
    edges = _labelled(_cfg("for item in items:\n    a()\nb()\n"))
    assert ("items", "each_item", "a") in edges
    assert ("a", "repeat", "items") in edges
    assert ("items", "exhausted", "b") in edges


def test_a_return_ends_the_path():
    """Nothing follows a return, so no edge may leave it."""
    graph = _cfg("def f():\n    return 1\n")
    returns = [step for step in graph["steps"] if step["parser_type_name"] == "Return"]
    assert returns
    assert not [edge for edge in graph["edges"] if edge["from"] == returns[0]["id"]]


def test_a_break_leaves_the_loop_rather_than_repeating_it():
    graph = _cfg("while cond:\n    if flag:\n        break\n    a()\nb()\n")
    by_id = {step["id"]: step for step in graph["steps"]}
    breaks = next(step for step in graph["steps"] if step["parser_type_name"] == "Break")
    outgoing = [edge for edge in graph["edges"] if edge["from"] == breaks["id"]]
    assert outgoing, "a break must reach the statement after the loop"
    assert all(by_id[edge["to"]]["callee"] == "b" for edge in outgoing)


def test_a_continue_goes_back_to_the_loop_header():
    graph = _cfg("while cond:\n    continue\n")
    by_id = {step["id"]: step for step in graph["steps"]}
    node = next(step for step in graph["steps"] if step["parser_type_name"] == "Continue")
    edges = [edge for edge in graph["edges"] if edge["from"] == node["id"]]
    assert [(edge["kind"], by_id[edge["to"]]["condition"]) for edge in edges] == [("repeat", "cond")]


def test_a_step_carries_its_callee_and_its_span():
    """The callee makes a step nameable; the span is the join key to a trace."""
    step = next(item for item in _cfg("charge(4.2)\n")["steps"] if item["callee"])
    assert step["callee"] == "charge"
    assert step["span"]["start_line"] == 1


def test_a_step_uses_the_neutral_node_type():
    """The Python label rides as a property, never as the node type."""
    step = next(item for item in _cfg("while cond:\n    a()\n")["steps"] if item["condition"])
    assert step["node_type"] == "ControlStructure"
    assert step["parser_type_name"] == "While"


def test_each_function_is_its_own_subgraph():
    """Control does not flow between functions without a call."""
    graph = _cfg("def f():\n    a()\n\ndef g():\n    b()\n")
    scopes = {step["scope"] for step in graph["steps"]}
    assert scopes == {"f", "g"}
    assert not _labelled(graph) & {("a", "next", "b")}


def test_the_real_procedure_reads_as_a_plan():
    edges = _labelled(_cfg(TIER2, module="battery.procedure"))
    assert ("i < cycles", "when_true", "charge") in edges
    assert ("charge", "next", "rest") in edges
    assert ("i += 1", "repeat", "i < cycles") in edges or any(
        kind == "repeat" and target == "i < cycles" for _, kind, target in edges
    )


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_corpus_file_builds_a_graph(path):
    graph = analyze(path.read_text(encoding="utf-8"), module=path.stem, file=path.name)
    assert graph["steps"], path
    known = {step["id"] for step in graph["steps"]}
    for edge in graph["edges"]:
        assert edge["from"] in known and edge["to"] in known, "no dangling edge"
        assert edge["kind"] in EDGE_KINDS


def _graph_of(source, module="battery.procedure"):
    document = as_document(analyze(source, module=module, file="procedure.py"))
    from awl.context import build_context

    document["@context"] = build_context()["@context"]
    graph = Graph()
    graph.parse(data=json.dumps(document), format="json-ld")
    return graph


def test_the_plan_is_queryable_as_a_path_expression():
    """Why edges are predicates and not reified nodes.

    Reifying would need two joins to cross one edge and would put the reason
    behind a literal comparison, so this query could not be written at all.
    The loop is selected by having a back edge, which is a structural fact,
    rather than by the text of its test, which is not.
    """
    rows = _graph_of(TIER2).query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee ?line WHERE {
          ?loop ^awl:repeat ?back ; awl:whenTrue/awl:next* ?step .
          ?step awl:callee ?callee ; awl:span [ awl:startLine ?line ] .
        } ORDER BY ?line
    """)
    assert [str(row[0]) for row in rows] == ["charge", "rest"]


def test_a_condition_records_the_names_it_reads():
    """The queryable half of a condition; the text is for display only."""
    step = next(item for item in _cfg("while i < cycles:\n    a()\n")["steps"] if item["condition"])
    assert step["condition_reads"] == ["i", "cycles"]
    assert step["condition"] == "i < cycles", "kept, but for rendering"


def test_the_back_edge_survives_the_projection():
    rows = _graph_of(TIER2).query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?condition WHERE { ?step awl:repeat ?loop . ?loop awl:condition ?condition }
    """)
    assert [str(row[0]) for row in rows] == ["i < cycles"]


def test_a_step_outside_the_loop_is_not_reachable_through_it():
    """Otherwise the plan would claim more than the code says."""
    rows = _graph_of("setup()\nwhile cond:\n    a()\n").query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee WHERE {
          ?loop awl:condition "cond" ; awl:whenTrue/awl:next* ?step .
          ?step awl:callee ?callee .
        }
    """)
    assert [str(row[0]) for row in rows] == ["a"]
