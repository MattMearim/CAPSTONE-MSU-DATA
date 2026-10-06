"""Adapter checks. The first test needs no downloaded data."""
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingestion import adapters  # noqa: E402

SCHEMAS = {p.name: json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.schema.json")}
REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()])


def errors(record):
    schema = SCHEMAS[f"{record['record_type']}.schema.json"]
    v = Draft202012Validator(schema, registry=REGISTRY, format_checker=FormatChecker())
    return [e.message for e in v.iter_errors(record)]


SOURCE = {"title": "fixture", "base_url": "https://example.invalid/", "license": "test"}


def test_skab_adapter_on_fixture(tmp_path):
    f = tmp_path / "1.csv"
    f.write_text(
        "datetime;Accelerometer1RMS;Current;anomaly;changepoint\n"
        "2020-03-09 10:14:33;0.02;1.3;0.0;0.0\n"
        "2020-03-09 10:14:34;;1.4;1.0;1.0\n"
        "2020-03-09 10:14:36;0.03;1.5;0.0;0.0\n"
    )
    ts, log = list(adapters.skab(f, SOURCE, "valve1/1.csv"))
    assert not errors(ts) and not errors(log)
    acc = ts["channels"][0]
    assert acc["values"] == [0.02, None, 0.03]          # blank cell kept as null
    assert acc["quality"] == ["good", "missing", "good"]
    assert ts["provenance"]["synthetic"] is False
    assert ts["event_id"] == log["event_id"]             # waveform and log are linked
    assert [e["name"] for e in log["events"]] == ["anomaly_label", "changepoint_label", "anomaly_label"]


def _converted():
    return sorted((ROOT / "data" / "converted").glob("*/*.json"))


@pytest.mark.skipif(not _converted(), reason="run scripts/fetch_data.py and scripts/convert_data.py first")
def test_all_converted_records_validate():
    bad = {}
    for path in _converted():
        errs = errors(json.loads(path.read_text()))
        if errs:
            bad[path.name] = errs[:2]
    assert not bad, bad
