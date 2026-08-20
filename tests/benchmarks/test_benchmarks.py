"""Performance benchmarks; run with `make bench`, never with the unit tests."""

from awl import AstSerialization

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
    result = benchmark(AstSerialization().parse, SOURCE)
    assert result["_type"] == "Module"


def test_unparse_benchmark(benchmark) -> None:
    """Baseline for AST document back to source."""
    serialization = AstSerialization()
    ast_dict = serialization.parse(SOURCE)
    result = benchmark(serialization.unparse, ast_dict)
    assert "def procedure" in result


def test_to_jsonld_benchmark(benchmark) -> None:
    """Baseline for the JSON-LD projection."""
    serialization = AstSerialization()
    serialization.parse(SOURCE)
    result = benchmark(serialization.to_jsonld)
    assert "@context" in result
