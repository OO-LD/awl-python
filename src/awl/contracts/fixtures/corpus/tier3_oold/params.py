"""Tier 3: parameter object in the OO-LD notation.

Exercises every declaration form M3 must recognise:

- a declared instance type, via the ``type`` field default;
- ``Link[T]`` inside the annotation;
- ``LinkedField(link=True)`` with a plain annotation, the alternative form;
- a union arm mixing a literal, an inline object and a reference.

This module is parsed statically and is deliberately not imported: the
notation lives on an experimental oold-python branch, so it may not be
installed. M3 does static analysis, so that is sufficient.
"""

from oold.experimental.notation import Link, LinkedBaseModel, LinkedField


class Device(LinkedBaseModel):
    id: str
    type: str | None = "ex:Device"
    serial: str | None = None


class ChargeParam(LinkedBaseModel):
    id: str | None = None
    type: str | None = "ex:ChargeParam"

    target_voltage: float
    c_rate: float

    # Link[T] inside the annotation.
    device: Link[Device] | None = None

    # The alternative form: plain annotation, link declared on the field.
    calibrated_against: Device | None = LinkedField(link=True)

    # Union arm: literal text, inline object, or reference by IRI.
    operator: str | Device | None = LinkedField(link=True)
