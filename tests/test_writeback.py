"""M10: applying editor changes back to source without disturbing trivia.

Imports only the module under test.
"""

from awl.writeback import apply_edits

SOURCE = """def procedure(cycles: int) -> None:
    # ramp to 4.2 V, CC phase only
    i = 0
    while i < cycles:
        charge(ChargeParam(target_voltage=4.2,   # cell limit per datasheet
                           c_rate=0.23))
        i += 1
"""


def test_editing_a_literal_preserves_every_comment_and_the_layout():
    patched = apply_edits(SOURCE, [{"start": 145, "end": 148, "text": "4.1"}])
    assert "target_voltage=4.1" in patched
    assert "# ramp to 4.2 V, CC phase only" in patched
    assert "# cell limit per datasheet" in patched
    assert patched.count("\n") == SOURCE.count("\n"), "no reflow"
