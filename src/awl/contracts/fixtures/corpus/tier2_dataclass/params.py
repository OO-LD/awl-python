"""Tier 2: parameter object as a plain dataclass."""

from dataclasses import dataclass


@dataclass
class ChargeParam:
    target_voltage: float
    c_rate: float
