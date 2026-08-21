# Vendored corpus file

Kept verbatim. Provenance lives here rather than in a header comment so the
sample stays byte-identical to its source.

## optimize_global.py

| | |
| --- | --- |
| Source | https://github.com/scipy/scipy/blob/main/doc/source/tutorial/examples/optimize_global_1.py |
| Repository | `scipy/scipy` |
| Path | `doc/source/tutorial/examples/optimize_global_1.py` |
| Blob SHA | `f78a6bb88ae62d541bed36e0d33dd89425b2b710` |
| Last commit touching it | `1dd843d4d68935aa5e5110f74e21c2121781e6d2` |
| Licence | BSD-3-Clause (scipy) |
| Retrieved | 2026-08-20 |
| Size | 49 lines, 32 calls, 1 loop |

### Why this file

Every other corpus file was written by us to be testable, which means the
whole suite risks validating against code shaped to pass. This one was not.

It also earns its place structurally: it is the **tier 1 counterpart of
`tier3_oold`**, so the tier table becomes a controlled comparison rather than
three unrelated samples.

| Property | Why it matters |
| --- | --- |
| Four opaque solver calls (`shgo`, `dual_annealing`, `differential_evolution`) whose results are bound to names | The same shape as `linregress` in the tensile test: an opaque numeric call producing a derived quantity, with no annotation to say what it means |
| Imports numpy and scipy | Exercises M11's C-callee naming, which `settrace` alone cannot see |
| A `for` loop over `range(...)` | Control flow, which is AWL-LD's differentiator and which the hand-written tier files keep deliberately simple |
| `results['shgo_sobol'].xl.shape[0]` | An attribute and subscript chain, the same class of problem as tracing back through `.pint.to_base_units().pint.magnitude` |
| A nested function definition (`plot_point`) closing over `ax` | A closure, which name resolution must not mistake for a module-level symbol |
| Roughly half the file is matplotlib plotting | Realistic noise. Real scientific scripts are not tidy, and the ambient-vocabulary filter has to cope |

### Updating it

Do not edit the file. If it needs refreshing, re-fetch from the source above
and update the SHAs here, so a diff in the fixture is always traceable to a
diff upstream.

## tensile_test.py

| | |
| --- | --- |
| Source | `opensemantic.characteristics.quantitative-python`, `examples/tensile_test.py` |
| Repository | `OpenSemanticLab/osw-package-maintenance` |
| Licence | same as the package it ships with; first-party to this organisation |
| Retrieved | 2026-08-21 |
| Size | 116 lines, 4 model classes, 1 analysis function |

### Why this file

It is the only sample in the corpus where the **semantic** question is
answerable end to end, and it is answerable without following the hard chain.

```py
class TensileTestSpecimen(OswBaseModel):
    e_mod: Optional[ModulusOfElasticity] = None

class TensileTestDataset(OswBaseModel):
    specimen: TensileTestSpecimen

def tensile_test_analysis(dataset: TensileTestDataset) -> TensileTestDataset:
    dataset.specimen.e_mod = ModulusOfElasticity.from_pint(slope.to("Pa"))
```

The parameter is annotated, and every hop of `dataset.specimen.e_mod` is a
declared field with a declared annotation. So "where was the modulus of
elasticity written, and to what" is a walk over declarations, and needs none of
the `linregress` or `.pint.magnitude` dataflow.

The same file also contains the chain that is **not** followable, in the same
function, which is why it is worth having both in one fixture:

```py
slope, *_ = linregress(
    linear["strain"].pint.to_base_units().pint.magnitude, ...
)
```

Four independent breaks there: the arguments are attribute chains rather than
typed constructor calls, so no argument types are observed; the name chain
truncates at the `linear["strain"]` subscript; `slope, *_ =` is a starred
destructuring; and `.pint.magnitude` deliberately erases the unit, which is
what that line is for. The call therefore stays uncollapsed and its binding
stays ambiguous, which is the intended outcome rather than a gap to paper over.

### Classes derive from OswBaseModel, not the linked base

So they produce declarations with fields and annotations, and no linked type
info. That is the point: member-path resolution works from ordinary annotated
classes, one rung below the linked notation.
