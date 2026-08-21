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

SPAN = {"file": "p.py", "startLine": 7, "startCol": 8, "endLine": 7, "endCol": 14}

FACTS = {
    "file": "procedure.py",
    "module": "procedure",
    "imports": [
        {
            "localName": "charge",
            "importedName": "charge",
            "fromModule": "battery.device",
            "isAlias": False,
            "isStar": False,
        }
    ],
    "uses": [{"localName": "charge", "span": SPAN}],
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
    by_name = {binding["localName"]: binding for binding in bindings}
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
            "localName": "*",
            "importedName": "*",
            "fromModule": "battery.device",
            "isAlias": False,
            "isStar": True,
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
            "localName": "Thing",
            "importedName": "Thing",
            "fromModule": "pkg",
            "isAlias": False,
            "isStar": False,
        }
    ]
    facts["uses"] = [{"localName": "Thing", "span": SPAN}]
    index = {
        "pkg": {
            "file": "pkg/__init__.py",
            "module": "pkg",
            "exports": [{"exportedName": "Thing", "module": "pkg", "fromModule": "pkg.impl"}],
        }
    }

    binding = resolve(facts, index=index)["bindings"][0]
    assert binding["confidence"] == "INFERRED", "following a re-export is a deduction"
    assert binding["identity"]["aliasOf"] == "pkg"
    assert binding["identity"]["aliasRoot"].endswith("pkg.impl/Thing")


def test_without_the_index_the_same_import_stays_extracted():
    """Per-file resolution reports what the source literally says.

    Downgrading to INFERRED without having read the other module would be
    inventing doubt, which is as wrong as inventing certainty.
    """
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "localName": "Thing",
            "importedName": "Thing",
            "fromModule": "pkg",
            "isAlias": False,
            "isStar": False,
        }
    ]
    facts["uses"] = [{"localName": "Thing", "span": SPAN}]
    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED"
    assert binding["identity"]["iri"].endswith("pkg/Thing")


def test_a_module_that_defines_the_name_is_not_a_re_export():
    """An export with no origin is a definition, so there is no hop to follow."""
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "localName": "Thing",
            "importedName": "Thing",
            "fromModule": "pkg",
            "isAlias": False,
            "isStar": False,
        }
    ]
    facts["uses"] = [{"localName": "Thing", "span": SPAN}]
    index = {"pkg": {"file": "pkg.py", "exports": [{"exportedName": "Thing", "module": "pkg"}]}}
    assert resolve(facts, index=index)["bindings"][0]["confidence"] == "EXTRACTED"


def test_an_aliased_import_resolves_to_the_original_name():
    """`import numpy as np` is ubiquitous, including in the real corpus file."""
    facts = copy.deepcopy(FACTS)
    facts["imports"] = [
        {
            "localName": "np",
            "importedName": "numpy",
            "fromModule": "",
            "isAlias": True,
            "isStar": False,
        }
    ]
    facts["uses"] = [{"localName": "np", "span": SPAN}]

    binding = resolve(facts)["bindings"][0]
    assert binding["confidence"] == "EXTRACTED", "an alias is local and unambiguous"
    assert binding["identity"]["iri"].endswith("numpy")
    assert binding["identity"]["aliasOf"] == "np", "the hop as written is kept"


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
    facts["uses"] = [{"localName": "handle", "span": SPAN}]

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
                        "localName": "Thing",
                        "importedName": "Thing",
                        "fromModule": "pkg",
                        "isAlias": False,
                        "isStar": False,
                    }
                ],
                "uses": [{"localName": "Thing", "span": SPAN}],
            },
            {"pkg": {"file": "p", "exports": [{"exportedName": "Thing", "fromModule": "pkg.impl"}]}},
        ),
        ({**copy.deepcopy(FACTS), "imports": []}, None),
    ):
        tiers.add(resolve(facts, index=index or {})["bindings"][0]["confidence"])
    assert tiers == {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def test_output_matches_the_contract():
    contracts.validate(resolve(FACTS), "resolved-names")
    contracts.validate(resolve(TIER2), "resolved-names")
