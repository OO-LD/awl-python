"""Observation of what the source says, with nothing inferred.

Imports only the module under test, awl.ids and the contracts package.
"""

from awl import contracts
from awl.facts import extract

TIER1 = contracts.CORPUS_DIR / "tier1_plain" / "procedure.py"
TIER2 = contracts.CORPUS_DIR / "tier2_dataclass" / "procedure.py"
TIER2_PARAMS = contracts.CORPUS_DIR / "tier2_dataclass" / "params.py"
TIER3 = contracts.CORPUS_DIR / "tier3_oold" / "params.py"


def _facts(path, module):
    return extract(path.read_text(encoding="utf-8"), module=module, file=path.name)


def test_records_imports_with_their_alias_hop():
    facts = _facts(TIER2, "tier2_dataclass.procedure")
    imported = {entry["local_name"]: entry for entry in facts["imports"]}
    assert imported["charge"]["from_module"] == "battery.device"
    assert imported["ChargeParam"]["from_module"] == ".params", "relative imports stay as written"


def test_an_aliased_import_keeps_both_names():
    """Kythe's aliases and aliases/root pair: a query picks its indirection level."""
    facts = extract("from a.b import C as D\n", module="m")
    entry = facts["imports"][0]
    assert entry["local_name"] == "D"
    assert entry["imported_name"] == "C"
    assert entry["is_alias"] is True
    assert facts["aliases"] == [{"local_name": "D", "alias_of": "C", "alias_root": "a.b.C"}]


def test_a_plain_import_records_the_bound_name():
    facts = extract("import numpy.linalg\nimport numpy as np\n", module="m")
    bound = {entry["local_name"]: entry["imported_name"] for entry in facts["imports"]}
    assert bound == {"numpy": "numpy.linalg", "np": "numpy"}


def test_a_star_import_is_recorded_and_never_resolved():
    """The sound answer is to make it illegal in the domain schema, not to guess."""
    facts = extract("from a.b import *\n", module="m")
    assert facts["imports"][0]["imported_name"] == "*"
    assert facts["imports"][0]["is_star"] is True


def test_every_call_site_becomes_a_use():
    """awl.resolve binds uses, so an unpopulated list silently disables resolution."""
    facts = _facts(TIER2, "tier2_dataclass.procedure")
    used = {entry["local_name"] for entry in facts["uses"]}
    assert {"charge", "rest", "ChargeParam"} <= used
    for use in facts["uses"]:
        assert use["span"]["start_line"] >= 1, "a use without a span cannot be attributed"


def test_a_use_records_its_argument_type_names():
    """awl.ids mints the typed instantiation from these, so an untyped call is
    distinguishable from a call on a known type.
    """
    facts = extract("charge(ChargeParam(target_voltage=4.2))\n", module="m")
    charge = next(entry for entry in facts["uses"] if entry["local_name"] == "charge")
    assert charge["argument_types"] == ["ChargeParam"]


def test_a_function_becomes_a_declaration():
    facts = _facts(TIER2, "tier2_dataclass.procedure")
    procedure = next(entry for entry in facts["declarations"] if entry["name"] == "procedure")
    assert procedure["kind"] == "function"
    assert [p["name"] for p in procedure["parameters"]] == ["cycles"]
    assert procedure["parameters"][0]["annotation"] == "int"


def test_module_level_names_become_exports():
    """What another module could import from here; the re-export input for resolution."""
    facts = _facts(TIER2, "tier2_dataclass.procedure")
    assert "procedure" in {entry["exported_name"] for entry in facts["exports"]}


def test_reads_both_link_declaration_forms():
    """Neither form is canonical, so both must produce the same TypeInfo shape."""
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}

    assert fields["device"]["declaration_form"] == "Link[T]"
    assert fields["device"]["is_link"] is True
    assert fields["device"]["target"] == "Device"

    assert fields["calibrated_against"]["declaration_form"] == "LinkedField(link=True)"
    assert fields["calibrated_against"]["is_link"] is True
    assert fields["calibrated_against"]["target"] == "Device"


def test_the_two_link_forms_agree_on_every_semantic_field():
    """The point of "neither is canonical", asserted rather than stated.

    They differ in `declaration_form` and in `annotation`, and must not differ
    anywhere else. Both exclusions are deliberate: `annotation` is the text as
    written, which is an observation, and the two forms genuinely write
    different text (`Link[Device] | None` against `Device | None`). Every
    field a consumer reasons with has to match.
    """
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}
    semantic = ("is_link", "is_many", "target", "arms")
    assert {key: fields["device"][key] for key in semantic} == {
        key: fields["calibrated_against"][key] for key in semantic
    }
    assert fields["device"]["annotation"] != fields["calibrated_against"]["annotation"]


def test_a_plain_field_is_not_a_link():
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}
    assert fields["target_voltage"]["is_link"] is False
    assert fields["target_voltage"]["target"] is None
    assert fields["target_voltage"]["declaration_form"] == "plain"


def test_a_numeric_field_carries_its_annotation():
    """The xsd:double coercion in awl.context is derived from this.

    Without it an integer-valued float field round-trips through JSON-LD as
    xsd:integer, which is the cross-language hazard the context exists to fix.
    """
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}
    assert fields["target_voltage"]["annotation"] == "float"


def test_union_arms_are_recorded():
    """literal | reference | embedded is what the collapse discriminates on."""
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    operator = next(f for f in charge["fields"] if f["name"] == "operator")
    assert "literal" in operator["arms"], "str arm"
    assert "reference" in operator["arms"], "Device by IRI"
    assert "embedded" in operator["arms"], "Device inline, which is a blank node"


def test_a_non_link_field_admits_only_a_literal():
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}
    assert fields["target_voltage"]["arms"] == ["literal"]


def test_a_list_of_links_is_many():
    facts = extract(
        "from oold.experimental.notation import Link, LinkedBaseModel\n"
        "class A(LinkedBaseModel):\n"
        "    friends: list[Link['A']] | None = None\n",
        module="m",
    )
    field = facts["types"][0]["fields"][0]
    assert field["is_many"] is True
    assert field["is_link"] is True
    assert field["target"] == "A", "a forward reference is still a target"


def test_the_type_field_default_is_recorded():
    """As written. The reference schemas write a bare term and let the class's
    own context say what it resolves to, so reading it is awl.context's job.
    """
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    assert charge["declared_types"] == ["ChargeParam"]


def test_a_list_valued_type_default_is_kept_whole():
    """The reference schemas write ["Diameter"], and it co-types."""
    facts = extract(
        "from oold.experimental.notation import LinkedBaseModel\n"
        "class D(LinkedBaseModel):\n"
        "    type: list[str] | None = ['Diameter', 'qudt:Quantity']\n",
        module="m",
    )
    assert facts["types"][0]["declared_types"] == ["Diameter", "qudt:Quantity"]


def test_a_class_context_is_read_from_json_schema_extra():
    """The class is the authority on what its own fields mean.

    Read in the form the reference schemas use: a plain object holding a
    prefix, the class term and the terms it declares.
    """
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    declared = charge["declared_context"]
    assert declared["ex"] == "https://example.org/battery#"
    assert declared["ChargeParam"] == "ex:ChargeParam"
    assert declared["target_voltage"] == {"@id": "ex:targetVoltage", "@type": "xsd:double"}


def test_a_class_that_declares_no_context_says_so_by_omission():
    """Absent, not empty: nothing declared is not the same as declaring nothing."""
    facts = _facts(TIER3, "tier3_oold.params")
    device = next(t for t in facts["types"] if t["identity"]["symbol"] == "Device")
    assert "declared_context" not in device


def test_the_pydantic_v1_config_form_is_read_too():
    """Both forms are in the corpus.

    The generated OpenSemanticLab packages are pydantic v1, so they write a
    nested Config with schema_extra rather than model_config.
    """
    facts = extract(
        "from oold.experimental.notation import LinkedBaseModel\n"
        "class D(LinkedBaseModel):\n"
        "    class Config:\n"
        "        schema_extra = {'@context': {'qudt': 'http://qudt.org/schema/qudt/'}}\n",
        module="m",
    )
    assert facts["types"][0]["declared_context"] == {"qudt": "http://qudt.org/schema/qudt/"}


def test_a_context_that_is_not_a_literal_is_not_guessed():
    """An expression cannot be read statically, and inventing one would be worse."""
    facts = extract(
        "from oold.experimental.notation import LinkedBaseModel\n"
        "class D(LinkedBaseModel):\n"
        "    model_config = ConfigDict(json_schema_extra={'@context': build()})\n",
        module="m",
    )
    assert "declared_context" not in facts["types"][0]


def test_a_non_literal_neighbour_does_not_cost_the_context():
    """Only the @context entry is evaluated, not the whole schema_extra.

    The generated packages routinely put computed values beside it, and a
    class whose title is an expression must not lose its semantics.
    """
    facts = extract(
        "from oold.experimental.notation import LinkedBaseModel\n"
        "class D(LinkedBaseModel):\n"
        "    model_config = ConfigDict(json_schema_extra={\n"
        "        'title': compute_title(),\n"
        "        '@context': {'qudt': 'http://qudt.org/schema/qudt/'},\n"
        "    })\n",
        module="m",
    )
    assert facts["types"][0]["declared_context"] == {"qudt": "http://qudt.org/schema/qudt/"}


def test_the_id_and_type_fields_are_not_data_fields():
    """They carry identity, not payload, so the collapse must not emit them."""
    facts = _facts(TIER3, "tier3_oold.params")
    charge = next(t for t in facts["types"] if t["identity"]["symbol"] == "ChargeParam")
    assert not {"id", "type"} & {f["name"] for f in charge["fields"]}


def test_a_dataclass_yields_fields_but_no_type_info():
    """Tier 2 is a rung, not a gap.

    A plain dataclass has no IRIs, so no TypeInfo. It does have fields,
    annotations and an import-path identity, so it must still produce a
    declaration. Without this, tier 1 and tier 2 are indistinguishable and the
    gradient has a cliff exactly where the corpus measures it.
    """
    facts = _facts(TIER2_PARAMS, "tier2_dataclass.params")

    assert facts["types"] == [], "no IRIs, so no TypeInfo"

    charge = next(entry for entry in facts["declarations"] if entry["name"] == "ChargeParam")
    assert charge["kind"] == "class"
    assert charge["identity"]["iri"].endswith("tier2_dataclass.params/ChargeParam")
    fields = {f["name"]: f for f in charge["fields"]}
    assert set(fields) == {"target_voltage", "c_rate"}
    assert fields["target_voltage"]["annotation"] == "float"


def test_the_gradient_is_measurable_across_the_tiers():
    """Each tier must yield strictly more than the one below it."""

    def counts(tier, name):
        source = (contracts.CORPUS_DIR / tier / name).read_text(encoding="utf-8")
        facts = extract(source, module=f"{tier}.{name[:-3]}")
        return len(facts["declarations"]), len(facts["types"])

    plain = counts("tier1_plain", "procedure.py")
    typed = counts("tier2_dataclass", "params.py")
    oold = counts("tier3_oold", "params.py")

    assert typed[0] > 0, "tier 2 declares fields"
    assert typed[1] == 0 and oold[1] > 0, "only tier 3 has declared IRIs"
    assert plain[1] == 0


def test_tier_one_still_yields_a_call_graph():
    """The lower bound: no semantics, but the calls and their order are there."""
    facts = _facts(TIER1, "tier1_plain.procedure")
    assert {"charge", "rest"} <= {entry["local_name"] for entry in facts["uses"]}
    assert facts["types"] == []
    procedure = next(entry for entry in facts["declarations"] if entry["name"] == "procedure")
    assert procedure["parameters"][0]["annotation"] is None, "nothing says what cycles is"


def test_nothing_is_imported_to_read_tier_three():
    """The notation lives on an experimental branch that need not be installed."""
    import sys

    assert "oold.experimental.notation" not in sys.modules
    _facts(TIER3, "tier3_oold.params")
    assert "oold.experimental.notation" not in sys.modules


def test_output_matches_the_contract():
    for path, module in (
        (TIER1, "tier1_plain.procedure"),
        (TIER2, "tier2_dataclass.procedure"),
        (TIER2_PARAMS, "tier2_dataclass.params"),
        (TIER3, "tier3_oold.params"),
    ):
        contracts.validate(_facts(path, module), "symbol-facts")


def test_the_real_corpus_file_is_read_without_error():
    """External validity: a scientific script nobody wrote for this project."""
    path = contracts.CORPUS_DIR / "real" / "optimize_global.py"
    facts = _facts(path, "real.optimize_global")
    contracts.validate(facts, "symbol-facts")
    assert facts["uses"], "a 32-call file yields uses"
