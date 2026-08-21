"""Reaching definitions and def-use edges.

Imports only the module under test and the contracts package.
"""

from awl import contracts
from awl.dataflow import analyze

TENSILE = (contracts.CORPUS_DIR / "real" / "tensile_test.py").read_text(encoding="utf-8")


def _analyze(source, module="m"):
    return analyze(source, module=module, file="sample.py")


def _closure(out, start):
    """Return every definition transitively reachable from *start*."""
    by_id = {entry["id"]: entry for entry in out["definitions"]}
    seen, frontier = set(), list(start)
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(by_id[current]["depends_on"])
    return {by_id[identity]["name"] for identity in seen}


def test_a_use_links_to_the_binding_that_produced_it():
    out = _analyze("def f():\n    a = 1\n    b = a + 2\n")
    definitions = {entry["name"]: entry for entry in out["definitions"]}
    assert definitions["b"]["depends_on"] == [definitions["a"]["id"]]


def test_a_definition_records_what_produced_it():
    out = _analyze("def f():\n    x = compute(1)\n")
    assert out["definitions"][0]["produced_by"] == "compute"


def test_a_parameter_is_a_definition():
    """Otherwise every chain rooted in an argument stops at nothing."""
    out = _analyze("def f(dataset):\n    x = dataset\n")
    kinds = {entry["name"]: entry["kind"] for entry in out["definitions"]}
    assert kinds["dataset"] == "parameter"


def test_a_name_bound_in_both_arms_reaches_through_both():
    """Taking only the most recent definition silently drops a dependency.

    This is the reason definitions are sets and are merged at every join.
    """
    out = _analyze("def f(flag, a, b):\n    if flag:\n        x = a\n    else:\n        x = b\n    y = x\n")
    y = next(entry for entry in out["definitions"] if entry["name"] == "y")
    assert len(y["depends_on"]) == 2, "both arms reach the use"
    assert _closure(out, y["depends_on"]) >= {"x", "a", "b"}


def test_a_branch_condition_is_a_dependency_of_what_the_branch_produced():
    """A value only exists because a test went one way; that is provenance."""
    out = _analyze("def f(flag, a):\n    if flag:\n        x = a\n")
    x = next(entry for entry in out["definitions"] if entry["name"] == "x")
    assert _closure(out, x["depends_on"]) >= {"a", "flag"}


def test_a_loop_carried_dependency_is_recorded():
    """`total = total + i` reads the previous iteration's binding."""
    out = _analyze("def f(items):\n    total = 0\n    for i in items:\n        total = total + i\n")
    totals = [entry for entry in out["definitions"] if entry["name"] == "total"]
    assert len(totals) > 1, "the loop rebinds it"
    assert _closure(out, totals[-1]["depends_on"]) >= {"i", "items"}


def test_an_augmented_assignment_reads_its_own_target():
    out = _analyze("def f(n):\n    i = 0\n    i += n\n")
    augmented = next(entry for entry in out["definitions"] if entry["kind"] == "augmented")
    assert _closure(out, augmented["depends_on"]) >= {"i", "n"}


def test_starred_unpacking_binds_the_named_element():
    """`slope, *_ = linregress(...)` is how the real file binds its result."""
    out = _analyze("def f(a):\n    slope, *_ = compute(a)\n")
    slope = next(entry for entry in out["definitions"] if entry["name"] == "slope")
    assert slope["produced_by"] == "compute"
    assert _closure(out, slope["depends_on"]) >= {"a"}


def test_a_member_write_carries_its_dependencies():
    out = _analyze("def f(dataset, value):\n    dataset.specimen.e_mod = wrap(value)\n")
    write = out["writes"][0]
    assert write["path"] == "dataset.specimen.e_mod"
    assert write["produced_by"] == "wrap"
    assert _closure(out, write["depends_on"]) >= {"value", "dataset"}


def test_provenance_runs_through_an_untypeable_chain():
    """The point of separating provenance from typing.

    `linear["strain"].pint.to_base_units().pint.magnitude` cannot be typed:
    the subscript breaks the name chain and the accessor deliberately erases
    the unit. It can still be traced, because tracing only needs to know the
    value flowed through, not what the calls mean.
    """
    out = analyze(TENSILE, module="tensile_test", file="tensile_test.py")
    write = next(entry for entry in out["writes"] if entry["path"].endswith("e_mod"))
    reached = _closure(out, write["depends_on"])
    assert {"slope", "linear", "df", "dataset"} <= reached, reached


def test_the_producing_call_is_recorded_along_the_chain():
    """linregress is opaque, and still nameable as the step that made the value."""
    out = analyze(TENSILE, module="tensile_test", file="tensile_test.py")
    produced = {entry["produced_by"] for entry in out["definitions"]}
    assert "linregress" in produced
    assert "dataset.result.to_df" in produced


def test_every_definition_has_a_stable_distinct_identity():
    out = analyze(TENSILE, module="tensile_test", file="tensile_test.py")
    identities = [entry["id"] for entry in out["definitions"]]
    assert len(identities) == len(set(identities)), "two bindings must never collide"
    assert all(identity.startswith("https://w3id.org/awl/") for identity in identities)


def test_two_functions_do_not_share_a_scope():
    """A name in one function must not reach a use in another."""
    out = _analyze("def f():\n    x = 1\n\ndef g():\n    y = x\n")
    y = next(entry for entry in out["definitions"] if entry["name"] == "y")
    assert y["depends_on"] == [], "x is not in scope here"


def test_the_whole_corpus_analyses_without_error():
    for path in contracts.corpus_files():
        out = analyze(path.read_text(encoding="utf-8"), module=path.stem, file=path.name)
        assert isinstance(out["definitions"], list), path


def test_an_import_is_a_definition():
    """An import is where a name comes from, so it is a binding like any other.

    Leaving it out left every imported callee with no reaching definition, so
    a chain ended at `linregress` instead of saying it came from scipy.
    """
    out = _analyze("from scipy.stats import linregress\nx = linregress(a)\n")
    entry = next(item for item in out["definitions"] if item["name"] == "linregress")
    assert entry["kind"] == "import"
    assert entry["produced_by"] == "scipy.stats.linregress"


def test_a_relative_import_keeps_the_origin_as_written():
    out = _analyze("from .params import ChargeParam\n")
    assert out["definitions"][0]["produced_by"] == ".params.ChargeParam"


def test_a_star_import_binds_nothing():
    """Nothing resolves these soundly, so no name is invented for one."""
    assert _analyze("from m import *\n")["definitions"] == []


def test_a_function_body_sees_the_module_bindings():
    """A call lives inside a function, and its callee is imported at module
    level. Starting the body from nothing made the two unreachable from each
    other, which is where provenance actually breaks.
    """
    out = _analyze("from m import g\n\ndef f(a):\n    return g(a)\n")
    call_site = next(item for item in out["definitions"] if item["name"] == "g")
    assert call_site["kind"] == "import"
    assert "g" in _closure(out, [call_site["id"]])


def test_a_caught_exception_is_bound():
    out = _analyze("try:\n    a()\nexcept E as err:\n    log(err)\n")
    assert [(e["name"], e["kind"]) for e in out["definitions"]] == [("err", "exception")]


def test_provenance_reaches_the_import_a_value_came_from():
    """The full chain on the real file, ending at a package rather than
    trailing off at a bare name.
    """
    out = analyze(TENSILE, module="tensile_test", file="tensile_test.py")
    write = next(entry for entry in out["writes"] if entry["path"].endswith("e_mod"))
    reached = _closure(out, write["depends_on"])
    assert {"linregress", "dataset", "df", "linear"} <= reached, reached
