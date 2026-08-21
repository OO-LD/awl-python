"""Tier 3: parameter object in the OO-LD notation.

Exercises every declaration form the extraction pass must recognise:

- a declared instance type, via the ``type`` field default;
- ``Link[T]`` inside the annotation;
- ``LinkedField(link=True)`` with a plain annotation, the alternative form;
- a union arm mixing a literal, an inline object and a reference;
- a declared ``@context``, which is pulled rather than generated.

``Device`` declares no context, so both halves stay exercised: what a class
says about itself, and what has to be inferred from annotations when it says
nothing.

This module is parsed statically and is deliberately not imported: the
notation lives on an experimental oold-python branch, so it may not be
installed. Extraction is static, so that is sufficient.
"""

from pydantic import ConfigDict

from oold.experimental.notation import Link, LinkedBaseModel, LinkedField


class Device(LinkedBaseModel):
    id: str
    type: str | None = "ex:Device"
    serial: str | None = None


class ChargeParam(LinkedBaseModel):
    # The class states what its own fields mean, in the form the reference
    # schemas use: a prefix, the class term, the type tag, then the terms.
    # See https://schemas.oo-ld.org/quantities/0.1/QuantityValue.schema.json.
    # Only target_voltage is declared, so c_rate still shows what a field the
    # class says nothing about gets.
    model_config = ConfigDict(
        json_schema_extra={
            "@context": {
                "ex": "https://example.org/battery#",
                "type": {"@id": "@type", "@container": "@set"},
                "ChargeParam": "ex:ChargeParam",
                "target_voltage": {"@id": "ex:targetVoltage", "@type": "xsd:double"},
            }
        }
    )

    id: str | None = None
    type: list[str] | None = ["ChargeParam"]

    target_voltage: float
    c_rate: float

    # Link[T] inside the annotation.
    device: Link[Device] | None = None

    # The alternative form: plain annotation, link declared on the field.
    calibrated_against: Device | None = LinkedField(link=True)

    # Union arm: literal text, inline object, or reference by IRI.
    operator: str | Device | None = LinkedField(link=True)
