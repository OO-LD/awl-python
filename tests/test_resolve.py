"""Binding names to identities, with the confidence of each binding.

Imports only the module under test, awl.ids and the contracts package. The
inputs are golden fixtures produced by the extraction pass, so a change in what
extraction emits fails here instead of silently drifting.
"""

import copy

import pytest

from awl import contracts
from awl.resolve import resolve

TIER2 = contracts.load_fixture("tier2-procedure-symbol-facts")

SPAN = {"file": "p.py", "start_line": 7, "start_col": 8, "end_line": 7, "end_col": 14}

FACTS = {
    "file": "procedure.py",
    "module": "procedure",
    "imports": [
        {
            "local_name": "charge",
            "imported_name": "charge",
            "from_module": "battery.device",
            "is_alias": False,
            "is_star": False,
        }
    ],
    "uses": [{"local_name": "charge", "span": SPAN}],
    "declarations": [],
    "aliases": [],
    "exports": [],
    "types": [],
}


def test_a_direct_import_is_extracted_not_inferred():
    binding = resolve(FACTS)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED"
    assert binding["identity"]["iri"].endswith("battery.device/charge")


def test_the_real_corpus_file_resolves_every_call():
    """The fixture is real extraction output, so this catches drift between
    what extraction emits and what resolution reads.
    """
    bindings = resolve(TIER2)["bindings"]
    by_name = {binding["local_name"]: binding for binding in bindings}
    assert {"charge", "rest", "ChargeParam"} <= set(by_name)
    for name in ("charge", "rest", "ChargeParam"):
        assert by_name[name]["confidence"] == "EXTRACTED", name
    assert by_name["charge"]["identity"]["iri"].endswith("battery.device/charge")
    assert by_name["ChargeParam"]["identity"]["iri"].endswith("params/ChargeParam")


def test_a_star_import_never_produces_an_identity():
    """No surveyed system resolves these soundly. Fabricating one would be
    worse than admitting ignorance, because a wrong identity merges two
    entities.
    """
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "local_name": "*",
            "imported_name": "*",
            "from_module": "battery.device",
            "is_alias": False,
            "is_star": True,
        }
    ]
    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "AMBIGUOUS"
    assert "identity" not in binding
    assert "star import" in binding["reason"]


def test_an_unknown_name_is_ambiguous_not_invented():
    facts = copy.deepcopy(FACTS)
    facts["imports"] = []
    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "AMBIGUOUS"
    assert "identity" not in binding


def test_a_locally_defined_function_resolves_to_this_module():
    facts = copy.deepcopy(FACTS)
    facts["imports"] = []
    facts["module"] = "battery.procedure"
    facts["declarations"] = [{"name": "charge", "kind": "function"}]
    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED"
    assert binding["identity"]["iri"].endswith("battery.procedure/charge")


def test_a_re_export_records_both_the_hop_and_the_root():
    """Kythe emits aliases and aliases/root so a query picks its indirection.

    Following the hop needs the intermediate module's own facts, which is why
    they arrive in an index rather than in the document under resolution:
    extraction is per file, so those facts come from two files.
    """
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "local_name": "Thing",
            "imported_name": "Thing",
            "from_module": "pkg",
            "is_alias": False,
            "is_star": False,
        }
    ]
    facts["uses"] = [{"local_name": "Thing", "span": SPAN}]
    index = {
        "pkg": {
            "file": "pkg/__init__.py",
            "module": "pkg",
            "exports": [{"exported_name": "Thing", "module": "pkg", "from_module": "pkg.impl"}],
        }
    }

    binding = resolve(facts, index=index)["bindings"][0]
    assert binding["confidence"] == "INFERRED", "following a re-export is a deduction"
    assert binding["identity"]["alias_of"] == "pkg"
    assert binding["identity"]["alias_root"].endswith("pkg.impl/Thing")


def test_without_the_index_the_same_import_stays_extracted():
    """Per-file resolution reports what the source literally says.

    Downgrading to INFERRED without having read the other module would be
    inventing doubt, which is as wrong as inventing certainty.
    """
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "local_name": "Thing",
            "imported_name": "Thing",
            "from_module": "pkg",
            "is_alias": False,
            "is_star": False,
        }
    ]
    facts["uses"] = [{"local_name": "Thing", "span": SPAN}]
    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED"
    assert binding["identity"]["iri"].endswith("pkg/Thing")


def test_a_module_that_defines_the_name_is_not_a_re_export():
    """An export with no origin is a definition, so there is no hop to follow."""
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "local_name": "Thing",
            "imported_name": "Thing",
            "from_module": "pkg",
            "is_alias": False,
            "is_star": False,
        }
    ]
    facts["uses"] = [{"local_name": "Thing", "span": SPAN}]
    index = {"pkg": {"file": "pkg.py", "exports": [{"exported_name": "Thing", "module": "pkg"}]}}
    assert resolve(facts, index=index)["bindings"][0]["confidence"] == "EXTRACTED"


def test_an_aliased_import_resolves_to_the_original_name():
    """`import numpy as np` is ubiquitous, including in the real corpus file."""
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "local_name": "np",
            "imported_name": "numpy",
            "from_module": "",
            "is_alias": True,
            "is_star": False,
        }
    ]
    facts["uses"] = [{"local_name": "np", "span": SPAN}]

    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED", "an alias is local and unambiguous"
    assert binding["identity"]["iri"].endswith("numpy")
    assert binding["identity"]["alias_of"] == "np", "the hop as written is kept"


@pytest.mark.parametrize(
    "declarations",
    [
        [
            {"name": "handle", "kind": "function", "decorators": ["singledispatch"]},
            {"name": "handle", "kind": "function", "decorators": ["handle.register"]},
        ],
        [{"name": "handle", "kind": "function", "decorators": ["typing.overload"]}],
    ],
    ids=["two definitions", "one marked overload"],
)
def test_an_overloaded_callee_is_ambiguous_until_disambiguated(declarations):
    """functools.singledispatch and typing.overload give one name several
    definitions. A bare fully qualified name cannot tell them apart, so picking
    the first would be a fabricated identity.
    """
    facts = copy.deepcopy(FACTS)
    facts["imports"] = []
    facts["declarations"] = declarations
    facts["uses"] = [{"local_name": "handle", "span": SPAN}]

    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "AMBIGUOUS"
    assert "identity" not in binding


def test_the_three_tiers_stay_distinguishable():
    """The property the whole confidence model exists for."""
    tiers = set()
    for facts, index in (
        (FACTS, None),
        (
            {
                **copy.deepcopy(FACTS),
                "imports": [
                    {
                        "local_name": "Thing",
                        "imported_name": "Thing",
                        "from_module": "pkg",
                        "is_alias": False,
                        "is_star": False,
                    }
                ],
                "uses": [{"local_name": "Thing", "span": SPAN}],
            },
            {"pkg": {"file": "p", "exports": [{"exported_name": "Thing", "from_module": "pkg.impl"}]}},
        ),
        ({**copy.deepcopy(FACTS), "imports": []}, None),
    ):
        tiers.add(resolve(facts, index=index or {})["bindings"][0]["confidence"])
    assert tiers == {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def test_output_matches_the_contract():
    contracts.validate(resolve(FACTS), "resolved-names")
    contracts.validate(resolve(TIER2), "resolved-names")


TENSILE = (contracts.CORPUS_DIR / "real" / "tensile_test.py").read_text(encoding="utf-8")

ALIASED = TENSILE.replace(
    '    dataset.specimen.e_mod = ModulusOfElasticity.from_pint(slope.to("Pa"))',
    '    s = dataset.specimen\n    s.e_mod = ModulusOfElasticity.from_pint(slope.to("Pa"))',
)


def _writes(source):
    from awl.facts import extract
    from awl.resolve import resolve_writes

    return resolve_writes(extract(source, module="tensile_test", file="tensile_test.py"))["writes"]


def _modulus(writes):
    return next(entry for entry in writes if entry.get("range_name") == "ModulusOfElasticity")


def test_a_member_write_is_resolved_to_its_declaring_class_and_range():
    """The semantic question: not "an attribute named e_mod", but "the modulus
    of elasticity of a tensile test specimen".
    """
    entry = _modulus(_writes(TENSILE))
    assert entry["member_path"] == "TensileTestDataset.specimen.e_mod"
    assert entry["member_of"].endswith("TensileTestSpecimen")
    assert entry["member"].endswith("TensileTestSpecimen/e_mod")
    assert entry["root_type"].endswith("TensileTestDataset")
    assert entry["written_by"] == "ModulusOfElasticity.from_pint"
    assert entry["confidence"] == "EXTRACTED"


def test_the_write_carries_the_span_so_the_answer_is_actionable():
    entry = _modulus(_writes(TENSILE))
    assert entry["span"]["start_line"] == 74
    assert TENSILE.splitlines()[73].strip().startswith("dataset.specimen.e_mod =")


def test_a_local_alias_does_not_change_what_the_code_means():
    """`s = dataset.specimen` then `s.e_mod = ...` must resolve identically.

    Introducing a local variable is a developer's convenience. If it changed
    the member, owner or root, every query would have to anticipate how the
    code happened to be written.
    """
    direct = _modulus(_writes(TENSILE))
    aliased = _modulus(_writes(ALIASED))
    for key in ("member_path", "member", "member_of", "root_type", "range", "written_by"):
        assert aliased[key] == direct[key], key


def test_an_alias_is_still_marked_as_a_deduction():
    """Transparent in the graph, distinguishable in confidence.

    No flow analysis is done, so a binding made inside a branch is assumed to
    reach a later write. That assumption has to stay visible.
    """
    assert _modulus(_writes(TENSILE))["confidence"] == "EXTRACTED"
    assert _modulus(_writes(ALIASED))["confidence"] == "INFERRED"


def test_an_unannotated_root_yields_no_member():
    """No parameter annotation, so nothing to walk. Ambiguous, not invented."""
    writes = _writes("def f(dataset):\n    dataset.specimen.e_mod = 1\n")
    assert writes[0]["confidence"] == "AMBIGUOUS"
    assert "member" not in writes[0]


def test_a_rebinding_to_something_unknown_drops_the_stale_type():
    """Otherwise a name keeps a type it no longer holds."""
    source = "class A:\n    b: int\n\ndef f(a: A):\n    x = a\n    x = compute()\n    x.b = 1\n"
    writes = _writes(source)
    assert writes[0]["confidence"] == "AMBIGUOUS"


def test_every_hop_of_the_chain_must_be_declared():
    """A path through an undeclared field resolves to nothing."""
    writes = _writes("class A:\n    b: int\n\ndef f(a: A):\n    a.nope.deeper = 1\n")
    assert writes[0]["confidence"] == "AMBIGUOUS"


def test_the_other_writes_in_the_real_file_resolve_too():
    """Not a single hand-picked case."""
    resolved = {entry["member_path"]: entry["range_name"] for entry in _writes(TENSILE) if entry.get("member_path")}
    assert resolved["TensileTestDataset.specimen.cross_section_area"] == "Area"
    assert resolved["TensileTestDataset.result"] == "TensileTestResult"
