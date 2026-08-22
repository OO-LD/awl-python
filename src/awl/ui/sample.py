"""The procedure the editor opens on, written to be edited and to be run.

The validation corpus is chosen to stress the *pipeline*: one function, an
import of hardware that is not attached, and no branch. That makes it a poor
thing to point an editor at. Every level below the module was empty, running it
needed stand-in modules before anything happened, and three of the seven edge
kinds the canvas can draw never appeared.

This is chosen to stress the *editor*, and it is a real module rather than a
fixture string so that ruff and the type checker keep it honest:

- four levels to descend through, ``procedure`` to ``charge`` and ``rest`` to
  ``settle``, so nesting is unlimited in fact and not only in principle;
- a branch and a loop, so ``when_true``, ``when_false`` and ``repeat`` are all
  on screen;
- a constructor with two typed fields, for the schema form;
- writes to a declared member, so a value can be followed to what it means;
- **no imports**, so the run button runs it and nothing has to be stubbed.
"""

from dataclasses import dataclass


@dataclass
class ChargeParam:
    """What one charge step is told to do."""

    target_voltage: float
    c_rate: float


@dataclass
class Report:
    """What the procedure produces."""

    cycles: int
    peak_voltage: float


def settle(seconds: int) -> None:
    """Let the cell relax. The bottom of the stack, and deliberately empty."""


def rest(seconds: int) -> None:
    """Hold the cell at rest for a while."""
    settle(seconds)


def charge(param: ChargeParam) -> float:
    """Drive the cell up to its target, and report what was reached."""
    voltage = 0.0
    while voltage < param.target_voltage:
        voltage += param.c_rate
    return voltage


def procedure(cycles: int) -> Report:
    """Charge and rest, and keep the highest voltage seen."""
    report = Report(cycles=0, peak_voltage=0.0)
    i = 0
    while i < cycles:
        peak = charge(ChargeParam(target_voltage=4.2, c_rate=0.35))
        if peak > report.peak_voltage:
            report.peak_voltage = peak
        rest(600)
        i += 1
    report.cycles = i
    return report
