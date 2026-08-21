"""Real-world example: tensile test analysis with stress-strain curve fitting."""

from typing import List, Optional

from scipy.stats import linregress

from opensemantic import OswBaseModel
from opensemantic.characteristics.quantitative import (
    Area,
    Force,
    ForcePerAreaUnit,
    ForceUnit,
    Length,
    LengthUnit,
    LinearStrain,
    ModulusOfElasticity,
    Stress,
    TabularData,
    Thickness,
    Width,
)


# Define the data model
class TensileTestSpecimen(OswBaseModel):
    length: Length
    width: Width
    thickness: Length
    cross_section_area: Optional[Area] = None
    e_mod: Optional[ModulusOfElasticity] = None


class TensileTestResultRow(OswBaseModel):
    elongation: Length
    force: Force
    strain: Optional[LinearStrain] = None
    stress: Optional[Stress] = None


class TensileTestResult(TabularData):
    rows: List[TensileTestResultRow]
    linear_region: Optional[LinearStrain] = LinearStrain(value=0.002)


class TensileTestDataset(OswBaseModel):
    specimen: TensileTestSpecimen
    result: TensileTestResult


def tensile_test_analysis(dataset: TensileTestDataset) -> TensileTestDataset:
    """Compute stress, strain, and modulus of elasticity from raw test data."""
    # Cross section area
    if dataset.specimen.cross_section_area is None:
        dataset.specimen.cross_section_area = (
            dataset.specimen.width * dataset.specimen.thickness
        )

    # Vectorized stress/strain via pint-pandas
    df = dataset.result.to_df()
    df["strain"] = df["elongation"] / dataset.specimen.length.to_pint()
    df["stress"] = df["force"] / dataset.specimen.cross_section_area.to_pint()

    # Linear regression on the elastic region
    linear = df[df["strain"] <= dataset.result.linear_region.to_pint()]
    slope, *_ = linregress(
        linear["strain"].pint.to_base_units().pint.magnitude,
        linear["stress"].pint.to_base_units().pint.magnitude,
    )
    slope = (
        slope
        * linear["stress"].pint.to_base_units().pint.units
        / linear["strain"].pint.to_base_units().pint.units
    )
    dataset.specimen.e_mod = ModulusOfElasticity.from_pint(slope.to("Pa"))
    dataset.result = TensileTestResult.from_df(df)
    return dataset


# Sample data
specimen = TensileTestSpecimen(
    length=Length(value=100, unit=LengthUnit.milli_meter),
    width=Width(value=10, unit=LengthUnit.milli_meter),
    thickness=Thickness(value=10, unit=LengthUnit.milli_meter),
)
result = TensileTestResult(
    rows=[
        TensileTestResultRow(
            force=Force(value=1.0, unit=ForceUnit.kilo_newton),
            elongation=Length(value=0.10, unit=LengthUnit.milli_meter),
        ),
        TensileTestResultRow(
            force=Force(value=1.505, unit=ForceUnit.kilo_newton),
            elongation=Length(value=0.15, unit=LengthUnit.milli_meter),
        ),
        TensileTestResultRow(
            force=Force(value=2.0, unit=ForceUnit.kilo_newton),
            elongation=Length(value=0.20, unit=LengthUnit.milli_meter),
        ),
    ]
)

dataset = TensileTestDataset(specimen=specimen, result=result)
analyzed = tensile_test_analysis(dataset)

print(
    f"Cross section area: {analyzed.specimen.cross_section_area.value} "
    f"{analyzed.specimen.cross_section_area.unit.name}"
)
print(
    f"Modulus of elasticity: {analyzed.specimen.e_mod.value} "
    f"{analyzed.specimen.e_mod.unit.name}"
)
assert analyzed.specimen.e_mod == ModulusOfElasticity(
    value=10.0, unit=ForcePerAreaUnit.giga_pascal
)
print("E = 10 GPa (as expected for this sample)")
