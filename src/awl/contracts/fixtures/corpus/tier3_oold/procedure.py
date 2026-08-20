"""Tier 3: OO-LD annotated Python.

Same computation as tiers 1 and 2. The call site is unchanged from tier 2,
and no IRI appears here: the semantics come from the resolved type, so the
collapse has everything it needs without the author writing linked data.
"""

from battery.device import charge, rest

from .params import ChargeParam


def procedure(cycles: int) -> None:
    i = 0
    while i < cycles:
        charge(ChargeParam(target_voltage=4.2, c_rate=0.23))
        rest(600)
        i += 1
