"""Performance benchmarks; run with `make bench`, never with the unit tests."""

import ast

from awl import compact, pipeline
from awl.astdoc import to_doc

SOURCE = """from battery.params import ChargeParam
from battery.device import charge, rest

def procedure(cycles: int) -> None:
    i = 0
    while i < cycles:
        charge(ChargeParam(target_voltage=4.2, c_rate=0.23))
        rest(600)
        i += 1
"""


def test_parse_benchmark(benchmark) -> None:
    """Baseline for source to AST document conversion."""
    result = benchmark(lambda: to_doc(ast.parse(SOURCE)))
    assert result["_type"] == "Module"


def test_compact_benchmark(benchmark) -> None:
    """Baseline for the editor model, which is what a UI holds."""
    result = benchmark(pipeline.to_compact, SOURCE, module="battery.procedure")
    assert result["@type"] == "Module"


def test_unparse_benchmark(benchmark) -> None:
    """Baseline for the editor model back to source."""
    doc = pipeline.to_compact(SOURCE, module="battery.procedure")
    result = benchmark(lambda: ast.unparse(ast.fix_missing_locations(compact.decode(doc))))
    assert "def procedure" in result


def test_to_graph_benchmark(benchmark) -> None:
    """Baseline for the RDF projection: tree, plan and def-use edges."""
    result = benchmark(pipeline.to_graph, SOURCE, module="battery.procedure")
    assert len(result) > 0
