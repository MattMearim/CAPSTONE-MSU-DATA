"""Checks that every example record validates against its schema.

Run from the repo root:  pytest
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
EXAMPLES = sorted((SCHEMA_DIR / "examples").glob("*.json"))


def _load(path):
    return json.loads(path.read_text())


def _registry():
    resources = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = _load(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _validator(record_type):
    schema = _load(SCHEMA_DIR / f"{record_type}.schema.json")
    return Draft202012Validator(schema, registry=_registry(), format_checker=FormatChecker())


def test_schemas_are_valid_json_schema():
    for path in SCHEMA_DIR.glob("*.schema.json"):
        Draft202012Validator.check_schema(_load(path))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_validates(path):
    record = _load(path)
    errors = list(_validator(record["record_type"]).iter_errors(record))
    assert not errors, [e.message for e in errors]


def test_synthetic_record_requires_generator():
    record = _load(SCHEMA_DIR / "examples" / "timeseries_rf.json")
    del record["provenance"]["generator"]
    assert list(_validator("timeseries").iter_errors(record))


def test_channel_needs_exactly_one_time_base():
    record = _load(SCHEMA_DIR / "examples" / "timeseries_rf.json")
    del record["channels"][0]["sample_rate_hz"]
    assert list(_validator("timeseries").iter_errors(record))


def test_no_domain_specific_fields():
    """The contract must stay field-agnostic: no schema may name a domain."""
    banned = {"rf", "cavity", "klystron", "plc", "vibration", "weather"}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        def keys(node):
            if isinstance(node, dict):
                for k, v in node.get("properties", {}).items():
                    yield k
                    yield from keys(v)
                for k in ("items", "then", "if"):
                    if k in node:
                        yield from keys(node[k])
        assert not banned & {k.lower() for k in keys(_load(path))}, path.name
