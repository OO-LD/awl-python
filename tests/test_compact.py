"""The compact AST codec, which is the editor's model.

Imports only the module under test, the contracts package and ast2json.
"""

import ast
import gzip
import json

import pytest
from ast2json import ast2json

from awl import contracts
from awl.compact import decode, encode

# Composition with the elision stage is asserted in tests/test_pipeline.py,
# which is the only suite allowed to import more than one module. Here the
# AstDoc-consumption property is asserted directly, by hand-annotating the
# input: see test_the_orderings_are_carried_through_unchanged.

TIER2 = contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py"


def test_round_trips_a_single_assignment():
    doc = ast2json(ast.parse("b = a + 2"))
    restored = decode(encode(doc))
    assert ast.unparse(ast.fix_missing_locations(restored)) == "b = a + 2"


def test_decoder_populates_every_field_of_the_node():
    """Asserting the fields are present is version-independent; asserting the
    failure mode is not.

    The package supports 3.11 upward. A decoder that only copies present keys
    passes on 3.13, which returns 'b = 1' for a Module with no type_ignores,
    and raises AttributeError on 3.11. So the test pins the invariant rather
    than the symptom.
    """
    node = decode(encode(ast2json(ast.parse("b = 1"))))
    missing = [field for field in type(node)._fields if not hasattr(node, field)]
    assert not missing, f"decoder left {missing} unreconstructed"


def test_encoder_drops_empty_required_lists():
    """Otherwise the test above passes vacuously."""
    assert "type_ignores" not in encode(ast2json(ast.parse("b = 1")))


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_round_trips_every_corpus_file(path):
    """Compared against unparse(tree), not against the source.

    ast.unparse normalises formatting and discards comments, so == source is
    unachievable and was measured failing on all 8 corpus files even with a
    correct implementation. Byte-level fidelity is the write-back guarantee, delivered
    by patching spans rather than by regenerating.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    restored = decode(encode(ast2json(tree)))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


def test_the_derivable_orderings_are_not_carried():
    """Array position already says it, so carrying a number repeats it.

    Duplicating it lets the two disagree: an editor that reorders a body and
    forgets to renumber leaves a document whose text and whose integers say
    different things. The RDF projection materializes them instead, because
    there position genuinely cannot be recovered.
    """
    doc = ast2json(ast.parse("f(1, x=2)"))
    call = doc["body"][0]["value"]
    call["args"][0]["argumentIndex"] = 1
    call["keywords"][0]["value"]["argumentIndex"] = -1
    call["keywords"][0]["value"]["argumentName"] = "x"
    call["order"] = 0

    blob = json.dumps(encode(doc))
    assert "argumentIndex" not in blob
    assert "argumentName" not in blob
    assert '"order"' not in blob


def test_an_ordering_does_not_force_a_literal_back_to_the_long_form():
    """A literal stays a literal; an ordering must not push it to the long form."""
    doc = ast2json(ast.parse("f(1)"))
    doc["body"][0]["value"]["args"][0]["argumentIndex"] = 1
    assert encode(doc)["body"][0]["value"]["args"][0] == {"literal": 1}


def test_compact_form_is_about_a_quarter_of_raw():
    """Measured on this file: 5425 bytes raw against roughly 1400 compact."""
    raw_doc = ast2json(ast.parse(TIER2.read_text(encoding="utf-8")))
    raw = len(json.dumps(raw_doc))
    assert len(json.dumps(encode(raw_doc))) / raw < 0.30


@pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_compaction_target_holds_across_the_corpus(path):
    """The outlier is the smallest file, where the fixed cost of the node
    labels is proportionally largest.

    The bound is loose on purpose. Keys are words rather than punctuation
    because the document is read and edited by hand, and the few percent that
    costs is a transport concern: see the compression test below.
    """
    raw_doc = ast2json(ast.parse(path.read_text(encoding="utf-8")))
    raw = len(json.dumps(raw_doc))
    assert len(json.dumps(encode(raw_doc))) / raw < 0.35


def test_spans_cost_roughly_fourteen_points_not_two():
    """Correcting a spec claim that was measured wrong.

    Spans were expected to cost about two percentage points. Measured on this
    file they cost 13.8 (24.5% to 38.3%), and up to 16.4 on the real corpus
    file, because a span rides on every expression node and not only on
    statements. Statement-only spans would be cheaper and would break the
    thing spans exist for: the tracer attributes events at expression level via
    co_positions(), and the editor edits a literal by its own span.
    """
    raw_doc = ast2json(ast.parse(TIER2.read_text(encoding="utf-8")))
    raw = len(json.dumps(raw_doc))
    without = len(json.dumps(encode(raw_doc))) / raw
    with_spans = len(json.dumps(encode(raw_doc, keep_spans=True))) / raw
    assert 0.10 < with_spans - without < 0.20
    assert with_spans < 0.50


def test_spans_are_available_when_requested():
    """Without these there is no join key between editor, trace and source."""
    doc = encode(ast2json(ast.parse("charge(ChargeParam(target_voltage=4.2))\n")), keep_spans=True)
    found = json.dumps(doc)
    assert '"span"' in found
    assert '"literal": 4.2' in found


def test_a_span_locates_the_literal_it_belongs_to():
    """The join key has to be right, not merely present."""
    source = "charge(ChargeParam(target_voltage=4.2))\n"
    doc = encode(ast2json(ast.parse(source)), keep_spans=True)
    literal = doc["body"][0]["value"]["args"][0]["keywords"][0]["value"]
    line, col, end_line, end_col = literal["span"]
    assert (line, end_line) == (1, 1)
    assert source[col:end_col] == "4.2"


def test_spans_are_absent_by_default():
    assert '"span"' not in json.dumps(encode(ast2json(ast.parse("x = 1\n"))))


def test_a_span_does_not_break_the_round_trip():
    """The editor decodes the same document it renders."""
    tree = ast.parse(TIER2.read_text(encoding="utf-8"))
    restored = decode(encode(ast2json(tree), keep_spans=True))
    assert ast.unparse(ast.fix_missing_locations(restored)) == ast.unparse(tree)


@pytest.mark.parametrize("keep_spans", [False, True])
def test_every_encoded_node_matches_the_contract(keep_spans):
    source = (contracts.CORPUS_DIR / "edge" / "if_else.py").read_text(encoding="utf-8")

    def walk(doc):
        if isinstance(doc, list):
            for item in doc:
                walk(item)
        elif isinstance(doc, dict):
            contracts.validate(doc, "compact-doc")
            for value in doc.values():
                walk(value)

    walk(encode(ast2json(ast.parse(source)), keep_spans=keep_spans))


def test_size_is_a_transport_concern_not_a_vocabulary_one():
    """Why readable keys are worth their bytes.

    Word keys repeat, so they compress almost perfectly. Choosing punctuation
    to save space would trade a permanent cost in readability against a saving
    that gzip already makes for free.
    """
    raw_doc = ast2json(ast.parse(TIER2.read_text(encoding="utf-8")))
    raw = json.dumps(raw_doc).encode()
    blob = json.dumps(encode(raw_doc)).encode()
    assert len(gzip.compress(blob)) < len(gzip.compress(raw)) / 1.5
    assert len(gzip.compress(blob)) < len(blob) / 2, "word keys compress away"
