"""Tier 2: typed Python, no linked data.

Same computation as tier 1, but the call now carries a named parameter
object. Field names and their Python types are recoverable; their meaning
is not, because nothing maps `target_voltage` to an IRI.
"""

from battery.device import charge, rest

from .params import ChargeParam


def procedure(cycles: int) -> None:
    i = 0
    while i < cycles:
        charge(ChargeParam(target_voltage=4.2, c_rate=0.23))
        rest(600)
        i += 1
