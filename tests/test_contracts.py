"""The contract schemas and the validation corpus.

Imports nothing but the module under test, which is the property that keeps
every other module independently implementable.
"""

import ast
import json

import pytest

from awl import contracts

EXPECTED_SCHEMAS = {
    "ast-doc",
    "compact-doc",
    "context-doc",
    "identity",
    "resolved-names",
    "source-span",
    "symbol-facts",
    "trace-event",
    "type-info",
}


def test_every_expected_schema_is_present():
    assert set(contracts.schema_names()) == EXPECTED_SCHEMAS


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_schema_is_a_valid_json_schema(name):
    """Each schema must be a legal JSON Schema 2020-12 document."""
    import jsonschema

    schema = contracts.load_schema(name)
    jsonschema.validators.validator_for(schema).check_schema(schema)


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_schema_is_an_oold_document(name):
    """Each schema doubles as a JSON-LD context and is versioned.

    This is what makes the contracts self-describing rather than just shapes.
    """
    schema = contracts.load_schema(name)
    assert "@context" in schema, "an OO-LD schema carries its own context"
    assert schema["$id"].startswith("https://w3id.org/awl/contracts/")
    assert schema["x-oold-version"]
    assert schema["title"]
    assert schema["description"]


def test_unknown_schema_name_lists_the_available_ones():
    with pytest.raises(FileNotFoundError, match="identity"):
        contracts.load_schema("no-such-schema")


def test_unknown_fixture_name_raises():
    with pytest.raises(FileNotFoundError):
        contracts.load_fixture("no-such-fixture")


class TestValidation:
    """validate() must resolve cross-schema refs without network access."""

    def test_accepts_a_conforming_identity(self):
        contracts.validate({"iri": "py:battery.params.ChargeParam", "scheme": "py"}, "identity")

    def test_rejects_an_identity_without_an_iri(self):
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            contracts.validate({"scheme": "py"}, "identity")

    def test_resolves_a_cross_schema_ref(self):
        """type-info refs identity and source-span by absolute IRI."""
        contracts.validate(
            {
                "identity": {"iri": "py:battery.params.ChargeParam", "scheme": "py"},
                "declaredTypes": ["ex:ChargeParam"],
                "fields": [
                    {
                        "name": "device",
                        "isLink": True,
                        "isMany": False,
                        "target": "Device",
                        "declarationForm": "Link[T]",
                        "arms": ["reference", "embedded"],
                    }
                ],
            },
            "type-info",
        )

    def test_rejects_an_unknown_declaration_form(self):
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            contracts.validate(
                {
                    "identity": {"iri": "py:x", "scheme": "py"},
                    "fields": [{"name": "f", "isLink": False, "isMany": False, "declarationForm": "invented"}],
                },
                "type-info",
            )

    def test_rejects_an_unknown_confidence_tier(self):
        """Retrofitted meaning must stay distinguishable from declared meaning."""
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            contracts.validate(
                {
                    "file": "procedure.py",
                    "bindings": [
                        {
                            "localName": "charge",
                            "span": {"file": "procedure.py", "startLine": 1, "startCol": 0, "endLine": 1, "endCol": 6},
                            "confidence": "PROBABLY",
                        }
                    ],
                },
                "resolved-names",
            )

    @pytest.mark.parametrize(
        "node",
        [
            {"type": "Call"},
            {"literal": 4.2},
            {"var": "cycles"},
        ],
    )
    def test_accepts_each_compact_node_form(self, node):
        contracts.validate(node, "compact-doc")

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param({"literal": 4.2, "extra": 1}, id="literal-with-stray-key"),
            pytest.param({"var": "i", "extra": 1}, id="name-with-stray-key"),
            pytest.param({}, id="empty"),
            pytest.param({"_": 7}, id="non-string-node-type"),
        ],
    )
    def test_rejects_a_node_matching_no_compact_form(self, node):
        """A compact node must match exactly one of the three forms.

        Note {"type": "Call"} is deliberately *not* rejected: a
        typed node carries arbitrary AST fields, one of which may be named c.
        """
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            contracts.validate(node, "compact-doc")


class TestCorpus:
    """The corpus is the evidence for the progressive-enhancement claim."""

    def test_all_tiers_are_present(self):
        tiers = {p.parent.name for p in contracts.corpus_files()}
        assert {"tier1_plain", "tier2_dataclass", "tier3_oold", "edge", "real"} <= tiers

    def test_a_real_world_file_is_vendored_with_provenance(self):
        """Everything else was written by us to be testable.

        Without at least one file we did not shape, the suite validates
        against code built to pass it.
        """
        real = contracts.CORPUS_DIR / "real"
        assert list(real.glob("*.py")), "no real-world sample"
        provenance = (real / "PROVENANCE.md").read_text(encoding="utf-8")
        for required in ("Blob SHA", "Licence", "Source"):
            assert required in provenance, f"{required} not recorded"

    def test_the_real_file_keeps_the_properties_it_was_chosen_for(self):
        """Guards against it being quietly replaced by another toy.

        Each assertion is a capability the rest of the corpus does not
        exercise: C callees, control flow, and an attribute/subscript chain.
        """
        source = next((contracts.CORPUS_DIR / "real").glob("*.py")).read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported = {
            node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        assert imported & {"numpy", "scipy"}, "must reach C callees"

        assert any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree)), "control flow"
        assert any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Subscript) for n in ast.walk(tree)), (
            "an attribute-on-subscript chain, as in the tensile test"
        )

    @pytest.mark.parametrize("path", contracts.corpus_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_corpus_file_parses(self, path):
        """Every corpus file must be parseable; tier 3 need not be importable."""
        ast.parse(path.read_text(encoding="utf-8"))

    def test_the_tiers_share_one_computation(self):
        """Only the annotation level differs, so the tiers are comparable.

        If this drifts, the corpus stops being a controlled comparison and the
        gradient claim becomes unmeasurable.
        """
        calls = {}
        for tier in ("tier1_plain", "tier2_dataclass", "tier3_oold"):
            src = (contracts.CORPUS_DIR / tier / "procedure.py").read_text(encoding="utf-8")
            tree = ast.parse(src)
            calls[tier] = sorted(
                n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            )
        assert calls["tier2_dataclass"] == calls["tier3_oold"]
        assert set(calls["tier1_plain"]) <= set(calls["tier2_dataclass"])

    def test_tier3_uses_both_link_declaration_forms(self):
        """Both forms are first class, so the corpus must exercise each."""
        src = (contracts.CORPUS_DIR / "tier3_oold" / "params.py").read_text(encoding="utf-8")
        assert "Link[Device]" in src, "the Link[T] annotation form"
        assert "LinkedField(link=True)" in src, "the field-declared form"


def test_schemas_are_serialisable_round_trip():
    """A schema must survive json round-tripping unchanged.

    Guards against a generator writing something json cannot reproduce.
    """
    for name in contracts.schema_names():
        schema = contracts.load_schema(name)
        assert json.loads(json.dumps(schema)) == schema
