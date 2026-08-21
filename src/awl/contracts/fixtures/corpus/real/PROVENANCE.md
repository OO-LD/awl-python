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
