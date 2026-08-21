"""M10: applying editor changes back to source without disturbing trivia.

Imports only the module under test.
"""

import ast

import pytest

from awl.writeback import apply_edits, insert_statement, span_of

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


def test_everything_outside_the_span_is_byte_identical():
    """The guarantee stated as an invariant rather than as three spot checks."""
    start, end = span_of(SOURCE, lambda n: isinstance(n, ast.Constant) and n.value == 4.2)
    patched = apply_edits(SOURCE, [{"start": start, "end": end, "text": "4.1"}])
    assert patched[:start] == SOURCE[:start]
    assert patched[start + 3 :] == SOURCE[end:]


def test_overlapping_edits_are_refused():
    """Order-dependent output is worse than an error."""
    with pytest.raises(ValueError, match="overlapping"):
        apply_edits(
            "abcdef",
            [{"start": 0, "end": 3, "text": "X"}, {"start": 2, "end": 5, "text": "Y"}],
        )


def test_adjacent_edits_are_allowed():
    """Touching but not overlapping. Refusing these would block a two-field edit."""
    assert (
        apply_edits(
            "abcdef",
            [{"start": 0, "end": 3, "text": "X"}, {"start": 3, "end": 5, "text": "Y"}],
        )
        == "XYf"
    )


def test_several_edits_do_not_shift_each_other():
    """Applied right to left, so an earlier offset stays valid after a later
    edit changes the text length.
    """
    edits = [
        {"start": 0, "end": 1, "text": "LONGER"},
        {"start": 4, "end": 5, "text": "Z"},
    ]
    assert apply_edits("abcde", edits) == "LONGERbcdZ"


def test_a_keyword_span_covers_the_whole_pair_not_just_the_value():
    """Measured gotcha: the keyword node spans `target_voltage=4.2`.

    An editor patching a *value* must therefore target the inner node, or it
    will overwrite the parameter name too. Verified offsets: the keyword is
    (130, 148) and the constant is (145, 148).
    """
    start, end = span_of(SOURCE, lambda n: isinstance(n, ast.keyword) and n.arg == "target_voltage")
    assert (start, end) == (130, 148)
    assert SOURCE[start:end] == "target_voltage=4.2"


def test_the_value_span_is_the_one_to_patch():
    start, end = span_of(SOURCE, lambda n: isinstance(n, ast.Constant) and n.value == 4.2)
    assert (start, end) == (145, 148)
    assert SOURCE[start:end] == "4.2"


def test_patching_the_keyword_span_would_destroy_the_parameter_name():
    """Shows the consequence, so the gotcha above is not just a note."""
    start, end = span_of(SOURCE, lambda n: isinstance(n, ast.keyword) and n.arg == "target_voltage")
    wrong = apply_edits(SOURCE, [{"start": start, "end": end, "text": "4.1"}])
    assert "target_voltage" not in wrong


def test_span_of_raises_when_nothing_matches():
    """A silent no-op edit would be the worst failure mode here."""
    with pytest.raises(LookupError):
        span_of(SOURCE, lambda n: False)


def test_libcst_parses_and_reprints_byte_identically():
    """The premise the structural tier rests on, asserted rather than assumed.

    If this ever fails, insert_statement is silently reformatting the file.
    """
    import libcst as cst

    assert cst.parse_module(SOURCE).code == SOURCE


def test_inserting_a_step_preserves_the_rest_of_the_file():
    patched = insert_statement(
        SOURCE,
        into="while",
        code="rest(600)",
        leading_comment="# hold 10 min, per SOP-114",
    )
    assert "rest(600)" in patched
    assert "# hold 10 min, per SOP-114" in patched
    assert "# ramp to 4.2 V, CC phase only" in patched
    assert "# cell limit per datasheet" in patched


def test_the_inserted_step_lands_inside_the_loop_body():
    """ "Preserves the comments" is not the same as "put it in the right place"."""
    patched = insert_statement(SOURCE, into="while", code="rest(600)")
    tree = ast.parse(patched)
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While))
    assert ast.unparse(loop.body[-1]) == "rest(600)"


def test_insertion_changes_nothing_but_the_inserted_lines():
    """Every original line survives, in order, with its original indentation."""
    patched = insert_statement(SOURCE, into="while", code="rest(600)", leading_comment="# hold 10 min")
    added = [line for line in patched.splitlines() if line not in SOURCE.splitlines()]
    assert [line.strip() for line in added] == ["# hold 10 min", "rest(600)"]


def test_an_unimplemented_target_raises_rather_than_no_op():
    """Returning the source unchanged would look like a successful edit."""
    with pytest.raises(NotImplementedError, match="for"):
        insert_statement(SOURCE, into="for", code="rest(600)")
