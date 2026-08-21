"""M2: the single identity-minting authority.

Imports only the module under test and the contracts package.
"""

from awl.ids import mint


def test_mints_an_iri_from_module_and_symbol():
    """Module and symbol are separated by "/", not ".", so the boundary
    survives. See test_module_and_symbol_boundaries_survive.
    """
    identity = mint(scheme="py", module="battery.params", symbol="ChargeParam")
    assert identity["iri"] == "https://w3id.org/awl/py/battery.params/ChargeParam"
    assert identity["scheme"] == "py"
