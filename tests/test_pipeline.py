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


def test_which_steps_repeat_and_what_governs_the_repetition():
    """The concrete measure of success, asked structurally.

    A loop is identified by having a back edge, not by the text of its test.
    Matching `awl:condition "i < cycles"` would work and would be worthless:
    it is unparsed source, so it breaks on a space or a rename, and it says
    nothing. What is queryable about a condition is the names it reads.
    """
    graph = pipeline.to_graph(_source(TIER2), module="battery.procedure", file="procedure.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee ?line WHERE {
          ?loop ^awl:repeat ?back ; awl:whenTrue/awl:next* ?step .
          ?step awl:callee ?callee ; awl:span [ awl:startLine ?line ] .
        } ORDER BY ?line
    """)
    assert [str(row[0]) for row in rows] == ["charge", "rest"]


def test_a_condition_links_to_the_bindings_it_reads():
    """A name would be scope-blind and would join to nothing.

    Pointing at the definition instead lets the query keep going: which steps
    repeat, governed by which binding, and where was that binding made.
    """
    graph = pipeline.to_graph(_source(TIER2), module="battery.procedure", file="procedure.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?callee ?governs ?bound_at WHERE {
          ?loop ^awl:repeat ?back ; awl:condition/awl:reads ?def ;
                awl:whenTrue/awl:next* ?step .
          ?step awl:callee ?callee .
          ?def awl:name ?governs ; awl:span [ awl:startLine ?bound_at ] .
        } ORDER BY ?callee ?governs
    """)
    assert [(str(a), str(b), int(c)) for a, b, c in rows] == [
        ("charge", "cycles", 13),
        ("charge", "i", 14),
        ("rest", "cycles", 13),
        ("rest", "i", 14),
    ]


def test_the_condition_join_is_by_span_not_by_name():
    """The plan and the def-use graph mint independently; only the span ties
    them, so a condition with no matching span gets no reads rather than a
    guess.
    """
    analysis = pipeline.analyze(_source(TIER2), module="battery.procedure", file="procedure.py")
    spans = {(entry["span"]["start_line"], entry["span"]["start_col"]) for entry in analysis["flow"]["conditions"]}
    plan_spans = {
        (step["condition"]["span"]["start_line"], step["condition"]["span"]["start_col"])
        for step in analysis["plan"]["steps"]
        if step.get("condition")
    }
    assert spans and spans == plan_spans


def test_which_step_follows_another():
    graph = pipeline.to_graph(_source(TIER2), module="battery.procedure", file="procedure.py")
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?next WHERE { ?a awl:callee "charge" ; awl:next ?b . ?b awl:callee ?next }
    """)
    assert [str(row[0]) for row in rows] == ["rest"]


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


def _tier(name):
    """Return a tier's procedure and an index holding the module it imports."""
    folder = contracts.CORPUS_DIR / name
    return (
        _source(folder / "procedure.py"),
        {f"{name}.params": _source(folder / "params.py")},
    )


def test_the_collapse_fires_across_modules():
    """A parameter object is defined in another file, essentially always.

    Without an index only classes declared beside the procedure could
    collapse, which is almost never where they live.
    """
    source, index = _tier("tier2_dataclass")
    doc = pipeline.to_compact(source, module="tier2_dataclass.procedure", index=index)
    node = doc["body"][3]["body"][1]["body"][0]["args"][0]
    assert node == {"@type": ["ChargeParam"], "target_voltage": 4.2, "c_rate": 0.23}


def test_without_the_index_nothing_is_collapsed():
    """Refusal, not a guess: the class was never read, so it is not named."""
    source, _ = _tier("tier2_dataclass")
    doc = pipeline.to_compact(source, module="tier2_dataclass.procedure")
    node = doc["body"][3]["body"][1]["body"][0]["args"][0]
    assert node["@type"] == "Call", "still a call, with its keywords intact"
    assert set(node["keyword_arguments"]) == {"target_voltage", "c_rate"}


def test_the_gradient_shows_in_the_collapsed_node():
    """The progressive-enhancement claim, made concrete rather than asserted.

    A plain dataclass collapses to its class name; the same computation in the
    linked notation adds the declared IRI. Same shape, more meaning.
    """
    plain = pipeline.to_compact(
        *_tier("tier2_dataclass")[:1], module="tier2_dataclass.procedure", index=_tier("tier2_dataclass")[1]
    )
    linked = pipeline.to_compact(*_tier("tier3_oold")[:1], module="tier3_oold.procedure", index=_tier("tier3_oold")[1])
    at = lambda d: d["body"][3]["body"][1]["body"][0]["args"][0]["@type"]
    assert at(plain) == ["ChargeParam"]
    assert at(linked) == ["ChargeParam", "ex:ChargeParam"]


def test_a_relative_import_is_resolved_against_the_importing_module():
    """`from .params import X` inside battery.procedure names battery.params."""
    assert pipeline.resolve_module("battery.procedure", ".params") == "battery.params"
    assert pipeline.resolve_module("a.b.c", "..d") == "a.d"
    assert pipeline.resolve_module("battery.procedure", "scipy.stats") == "scipy.stats"


def test_a_collapsed_document_still_regenerates_its_source():
    """Collapsing across modules must not cost the round trip."""
    source, index = _tier("tier3_oold")
    doc = pipeline.to_compact(source, module="tier3_oold.procedure", index=index)
    restored = ast.unparse(ast.fix_missing_locations(compact.decode(doc)))
    assert restored == ast.unparse(ast.parse(source))


def test_the_collapsed_fields_reach_rdf_as_properties_of_the_type():
    """The defect the embedded context was invented for, over the whole chain."""
    source, index = _tier("tier3_oold")
    graph = pipeline.to_graph(source, module="tier3_oold.procedure", index=index)
    rows = graph.query("""
        PREFIX awl: <https://w3id.org/awl/schema/>
        SELECT ?voltage WHERE { ?p a <https://w3id.org/awl/py/tier3_oold.params/ChargeParam> ;
                                   awl:target_voltage ?voltage }
    """)
    assert [float(row[0]) for row in rows] == [4.2]
