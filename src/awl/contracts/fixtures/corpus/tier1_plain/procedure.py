"""Tier 1: plain Python. No annotations anywhere.

The parameters cross the call boundary as bare floats, so nothing in the
source says what 4.2 or 0.23 mean. This is the lower bound of the gradient:
a call graph with control flow and literals, and no semantics.
"""

from battery.device import charge, rest


def procedure(cycles):
    i = 0
    while i < cycles:
        charge(4.2, 0.23)
        rest(600)
        i += 1
