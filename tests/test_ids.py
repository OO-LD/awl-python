"""The single identity-minting authority.

Imports only the module under test and the contracts package.
"""

import pytest

from awl.ids import class_identity, mint, mint_instantiation, normalize


def test_mints_an_iri_from_module_and_symbol():
    """Module and symbol are separated by "/", not ".", so the boundary
    survives. See test_module_and_symbol_boundaries_survive.
    """
    identity = mint(scheme="py", module="battery.params", symbol="ChargeParam")
    assert identity["iri"] == "https://w3id.org/awl/py/battery.params/ChargeParam"
    assert identity["scheme"] == "py"


SAMPLES = ["ChargeParam", "charge_param", "Ärger", "İslemYap", "a..b", "  x  ", "Straße"]


@pytest.mark.parametrize("text", SAMPLES)
def test_normalize_is_idempotent(text):
    assert normalize(normalize(text)) == normalize(text)


@pytest.mark.parametrize(
    "left,right",
    [("battery.Params", "battery.params"), ("ChargeParam", "chargeParam")],
)
def test_case_is_significant(left, right):
    """Python is case-sensitive, so these name different things.

    Casefolding, as graphify/ids.py does, merges them. That is a false merge,
    which is harder to notice than a false split because the graph simply
    contains one node where it should contain two.
    """
    assert normalize(left) != normalize(right)


def test_module_and_symbol_boundaries_survive():
    """a.b::C and a::b.C are different entities and must mint differently.

    Joining with "." loses the boundary and both flatten to a.b.C.
    """
    assert mint(scheme="py", module="a.b", symbol="C")["iri"] != mint(scheme="py", module="a", symbol="b.C")["iri"]


def test_a_version_distinguishes_two_revisions_of_one_class():
    """OO-LD classes may be versioned, from x-oold-version or a versioned $id."""
    unversioned = mint(scheme="py", module="battery.params", symbol="ChargeParam")
    versioned = mint(scheme="py", module="battery.params", symbol="ChargeParam", version="1.2.0")
    assert versioned["iri"] == f"{unversioned['iri']}@1.2.0"
    assert versioned["version"] == "1.2.0"


def test_an_unknown_version_is_left_empty_not_guessed():
    """Leaving the slot empty is the decision; a guessed version is a false claim."""
    assert mint(scheme="py", module="scipy.stats", symbol="linregress")["version"] is None


def test_the_minted_iri_is_always_resolvable():
    """A declared type never replaces the minted IRI.

    Declared types are usually CURIEs against a prefix this package does not
    control. Using one as the identity produced `ex:ChargeParam#target_voltage`
    predicates, which validate and join with nothing.
    """
    identity = class_identity(
        scheme="py",
        module="battery.params",
        symbol="ChargeParam",
        instance_rdf_types=["ex:ChargeParam"],
    )
    assert identity["iri"].startswith("https://w3id.org/awl/")
    assert identity["iri"].endswith("battery.params/ChargeParam")


def test_declared_types_are_carried_in_precedence_order():
    """x-oold-instance-rdf-type co-types, so every declared IRI is kept."""
    identity = class_identity(
        scheme="py",
        module="battery.params",
        symbol="ChargeParam",
        instance_rdf_types=["ex:ChargeParam", "qudt:QuantityValue"],
        type_field_default=["ex:Ignored"],
    )
    assert identity["declared_types"] == ["ex:ChargeParam", "qudt:QuantityValue"]


def test_the_type_field_default_is_used_when_no_schema_declaration():
    identity = class_identity(
        scheme="py",
        module="battery.params",
        symbol="ChargeParam",
        type_field_default="ex:ChargeParam",
    )
    assert identity["declared_types"] == ["ex:ChargeParam"]


def test_an_undeclared_class_has_no_declared_types():
    identity = class_identity(scheme="py", module="battery.params", symbol="ChargeParam")
    assert identity["iri"].endswith("battery.params/ChargeParam")
    assert identity["declared_types"] == []


def test_a_generic_callee_and_its_instantiation_differ():
    """The whole point: linregress carries no semantics, the instantiation may."""
    generic = mint(scheme="py", module="scipy.stats", symbol="linregress")
    typed = mint_instantiation(generic, ["LinearStrain", "Stress"])
    assert typed["iri"] != generic["iri"]
    assert typed["iri"].startswith(generic["iri"])


def test_identity_validates_against_the_contract():
    from awl import contracts

    contracts.validate(mint(scheme="py", module="a", symbol="B"), "identity")


def test_a_class_identity_validates_against_the_contract():
    """declared_types is part of the contract, not an undeclared extra.

    awl.facts and awl.collapse read it, so it needs a schema entry or they are consuming a
    field no contract describes.
    """
    from awl import contracts

    identity = class_identity(scheme="py", module="a", symbol="B", instance_rdf_types=["ex:B"])
    contracts.validate(identity, "identity")
    assert "declared_types" in contracts.load_schema("identity")["properties"]
