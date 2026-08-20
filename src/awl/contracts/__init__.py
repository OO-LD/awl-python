"""Contracts: the schemas and fixtures every other AWL-LD module is built against.

This package is the only shared dependency in the architecture. A module
depends on another module's *data contract*, never on its *code*, so each one
can be written, tested and replaced independently. That is only true as long
as the contracts here stay frozen, so treat a change to a schema as a change
to every module that reads it.

Schemas are OO-LD documents: each is simultaneously a JSON Schema 2020-12 and
a JSON-LD context, so a fixture can be validated and projected to RDF from one
source.

Examples
--------
>>> from awl import contracts
>>> "iri" in contracts.load_schema("identity")["properties"]
True
>>> contracts.validate({"iri": "py:battery.params", "scheme": "py"}, "identity")
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "CORPUS_DIR",
    "FIXTURES_DIR",
    "SCHEMAS_DIR",
    "corpus_files",
    "load_fixture",
    "load_schema",
    "schema_names",
    "validate",
]

SCHEMAS_DIR = Path(__file__).parent / "schemas"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORPUS_DIR = FIXTURES_DIR / "corpus"


def schema_names() -> list[str]:
    """Return every available schema name, sorted.

    Returns
    -------
    list of str
        Names without the ``.schema.json`` suffix, e.g. ``["ast-doc", ...]``.
    """
    return sorted(p.name.removesuffix(".schema.json") for p in SCHEMAS_DIR.glob("*.schema.json"))


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load one contract schema by name.

    Parameters
    ----------
    name : str
        Schema name without the suffix, e.g. ``"identity"``.

    Returns
    -------
    dict
        The parsed schema.

    Raises
    ------
    FileNotFoundError
        If no schema of that name exists. The message lists the available ones,
        because a typo here is otherwise hard to spot.
    """
    path = SCHEMAS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"no contract schema {name!r}; available: {', '.join(schema_names())}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture(name: str) -> Any:
    """Load one golden fixture by name.

    Parameters
    ----------
    name : str
        Fixture name without the ``.json`` suffix, e.g. ``"tier2-ast-doc"``.

    Returns
    -------
    Any
        The parsed fixture.

    Raises
    ------
    FileNotFoundError
        If no fixture of that name exists.
    """
    path = FIXTURES_DIR / f"{name}.json"
    if not path.is_file():
        available = sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))
        raise FileNotFoundError(f"no fixture {name!r}; available: {', '.join(available) or '(none)'}")
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_files() -> list[Path]:
    """Return every Python file in the validation corpus, sorted.

    The corpus is organised as annotation tiers over the same computation, so
    the progressive-enhancement claim can be measured rather than asserted.

    Returns
    -------
    list of pathlib.Path
    """
    return sorted(CORPUS_DIR.rglob("*.py"))


@lru_cache(maxsize=1)
def _registry() -> Any:
    """Build a referencing registry over the local schemas.

    Schemas cross-reference each other by absolute ``$id``. Without this every
    ``$ref`` would be resolved over the network, which would make validation
    depend on the internet and on w3id.org being reachable.
    """
    from referencing import Registry, Resource

    resources = []
    for name in schema_names():
        schema = load_schema(name)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(instance: Any, schema_name: str) -> None:
    """Validate an instance against a contract schema.

    Cross-schema ``$ref`` targets resolve locally, so this never touches the
    network.

    Parameters
    ----------
    instance : Any
        The document to check.
    schema_name : str
        Schema name without the suffix.

    Raises
    ------
    jsonschema.ValidationError
        If the instance does not conform.
    ImportError
        If ``jsonschema`` is not installed. It is a development dependency
        only, so that importing the contracts at runtime stays cheap.
    """
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - exercised only without the dev extra
        raise ImportError("validate() needs jsonschema, which is a development dependency") from exc

    schema = load_schema(schema_name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema, registry=_registry()).validate(instance)
