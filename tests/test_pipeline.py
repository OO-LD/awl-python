"""End to end. The only suite allowed to import more than one module.

What is worth testing here is not that each stage works, which its own suite
covers, but the failures no single stage can see: two producers naming one
entity differently, or a stage emitting something the next one cannot read.
"""

import ast

import pytest

from awl import compact, contracts, pipeline

TIER2 = contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py"
TIER3 = contracts.CORPUS_DIR / "tier3_oold" / "params.py"
TENSILE = contracts.CORPUS_DIR / "real" / "tensile_test.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_the_chain_runs_end_to_end():
    graph = pipeline.to_graph(_source(TIER2), module="battery.procedure", file="procedure.py")
    assert len(graph) > 0, "source to facts to resolve to elide to collapse to rdf"


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_corpus_file_survives_the_whole_chain(path):
    graph = pipeline.to_graph(_source(path), module=path.stem, file=path.name)
    assert len(graph) > 0, path


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_editor_model_regenerates_every_corpus_file(path):
    """The claim the whole compact path exists for, composed rather than
    exercised stage by stage.
    """
    source = _source(path)
    restored = compact.decode(pipeline.to_compact(source, module=path.stem))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(ast.parse(source))


def test_producers_agree_on_identity():
    """The failure no unit test can see.

    Five producers mint IRIs. If two name one entity differently the graph
    holds two disconnected nodes where it should hold one, and every unit
    suite still passes because each producer is self-consistent.
    """
    analysis = pipeline.analyze(_source(TENSILE), module="tensile_test", file="tensile_test.py")

    declared = {
        entry["name"]: entry["identity"]["iri"]
        for entry in analysis["facts"]["declarations"]
        if entry["kind"] == "class"
    }
    assert declared, "the file declares classes"

    written = {entry["member_of"] for entry in analysis["writes"]["writes"] if entry.get("member_of")}
    assert written, "and writes to members of them"
    unknown = written - set(declared.values())
    assert not unknown, f"member writes name classes extraction never minted: {unknown}"


def test_the_scopes_two_producers_use_are_the_same_names():
    """The def-use graph and the plan both scope by function.

    They mint independently, so a disagreement here would split one function's
    steps from its definitions with nothing to join them.
    """
    source = _source(TENSILE)
    analysis = pipeline.analyze(source, module="tensile_test", file="tensile_test.py")
    functions = {entry["name"] for entry in analysis["facts"]["declarations"] if entry["kind"] == "function"}
    flow_scopes = {entry["scope"] for entry in analysis["flow"]["definitions"] if entry["scope"]}
    plan_scopes = {step["scope"] for step in analysis["plan"]["steps"] if step["scope"]}

    assert flow_scopes <= functions, f"def-use invented scopes: {flow_scopes - functions}"
    assert plan_scopes <= functions, f"the plan invented scopes: {plan_scopes - functions}"
    assert flow_scopes == plan_scopes, "the two disagree about which functions exist"


def test_every_minted_identity_is_globally_scoped():
    """A relative or bare identifier would collide across modules."""
    analysis = pipeline.analyze(_source(TIER3), module="tier3_oold.params", file="params.py")
    minted = [
        *(entry["identity"]["iri"] for entry in analysis["facts"]["declarations"]),
        *(entry["id"] for entry in analysis["flow"]["definitions"]),
        *(step["id"] for step in analysis["plan"]["steps"]),
    ]
    assert minted
    assert all(iri.startswith("https://w3id.org/awl/") for iri in minted)


def test_two_modules_do_not_collide():
    """The same source under two module paths must mint two sets of names."""
    source = "def procedure():\n    charge()\n"
    first = pipeline.analyze(source, module="battery.a", file="a.py")
    second = pipeline.analyze(source, module="battery.b", file="b.py")
    left = {step["id"] for step in first["plan"]["steps"]}
    right = {step["id"] for step in second["plan"]["steps"]}
    assert left and not (left & right)


def test_the_plan_and_the_document_describe_the_same_steps():
    """Both carry spans, which is the only thing joining them."""
    source = _source(TIER2)
    analysis = pipeline.analyze(source, module="battery.procedure", file="procedure.py")
    callees = {step["callee"] for step in analysis["plan"]["steps"] if step["callee"]}
    assert {"charge", "rest"} <= callees

    compact = pipeline.to_compact(source, module="battery.procedure", spans=True)
    spans = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "span" in node:
                spans.add(tuple(node["span"][:2]))
            for value in node.values():
                walk(value)

    walk(compact)
    plan_spans = {
        (step["span"]["start_line"], step["span"]["start_col"]) for step in analysis["plan"]["steps"] if step["span"]
    }
    assert plan_spans & spans, "no span joins the plan to the document"


def test_the_ordering_query_the_design_was_measured_against():
    """The concrete measure of success, over the whole chain rather than a
    hand-built document: which steps run in the loop, in order.
    """
    graph = pipeline.to_graph(_source(TIER2), module="battery.procedure", file="procedure.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee ?line WHERE {
          ?loop awl:condition "i < cycles" ; awl:whenTrue/awl:next* ?step .
          ?step awl:callee ?callee ; awl:span [ awl:startLine ?line ] .
        } ORDER BY ?line
    """)
    assert [str(row[0]) for row in rows] == ["charge", "rest"]


def test_the_semantic_question_over_the_whole_chain():
    """Where was the modulus of elasticity written, to what, and by what."""
    graph = pipeline.to_graph(_source(TENSILE), module="tensile_test", file="tensile_test.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?path ?line ?writer WHERE {
          ?w awl:rootType <https://w3id.org/awl/py/tensile_test/TensileTestDataset> ;
             awl:memberPath ?path ; awl:writtenBy ?writer ;
             awl:span [ awl:startLine ?line ] .
          ?w awl:range <https://w3id.org/awl/py/opensemantic.characteristics.quantitative/ModulusOfElasticity> .
        }
    """)
    assert [(str(p), int(line), str(w)) for p, line, w in rows] == [
        ("TensileTestDataset.specimen.e_mod", 74, "ModulusOfElasticity.from_pint")
    ]


def test_value_provenance_over_the_whole_chain():
    """What the modulus depended on, through a chain that cannot be typed."""
    graph = pipeline.to_graph(_source(TENSILE), module="tensile_test", file="tensile_test.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT DISTINCT ?name WHERE {
          ?d awl:producedBy "linregress" ; awl:dependsOn+ ?upstream .
          ?upstream awl:name ?name .
        }
    """)
    reached = {str(row[0]) for row in rows}
    assert {"linear", "df", "dataset"} <= reached, reached
