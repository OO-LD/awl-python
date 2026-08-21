"""M2: the single identity-minting authority.

Imports only the module under test and the contracts package.
"""

import pytest

from awl.ids import mint, normalize


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
