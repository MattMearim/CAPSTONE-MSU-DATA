"""Generator checks: valid, reproducible, and field-agnostic."""
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from generator import engine  # noqa: E402

SCHEMAS = {p.name: json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.schema.json")}
REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()])


def errors(record):
    v = Draft202012Validator(SCHEMAS[f"{record['record_type']}.schema.json"],
                             registry=REGISTRY, format_checker=FormatChecker())
    return [e.message for e in v.iter_errors(record)]


def channel(record, name):
    return next(c for c in record["channels"] if c["name"] == name)


def test_every_record_validates():
    records, manifest = engine.generate(seed=3, events=45)
    assert manifest["counts"]["events"] == 45
    bad = {r["record_id"]: errors(r)[:2] for r in records if errors(r)}
    assert not bad, bad


def test_same_seed_same_output():
    a = json.dumps(engine.generate(seed=11, events=12))
    b = json.dumps(engine.generate(seed=11, events=12))
    c = json.dumps(engine.generate(seed=12, events=12))
    assert a == b and a != c


def test_covers_three_domains_and_every_scenario():
    _, manifest = engine.generate(seed=1, events=150)
    seen = {(e["domain"], e["scenario"]) for e in manifest["events"]}
    wanted = {(n, s["id"]) for n, d in engine.load_domains().items() for s in d["scenarios"]}
    assert {d for d, _ in seen} >= {"rf", "mechanical", "plc"}
    assert seen == wanted


def test_fault_shapes_match_their_description():
    records, manifest = engine.generate(seed=5, events=6, domains=["rf"], scenario="field_collapse")
    ts = next(r for r in records if r["record_type"] == "timeseries")
    field = [v for v in channel(ts, "cavity_field")["values"] if v is not None]
    assert field[100] > 4 and field[-1] < 0.1            # healthy before, collapsed after

    records, _ = engine.generate(seed=5, events=4, domains=["plc"], scenario="stale_sensor")
    ts = next(r for r in records if r["record_type"] == "timeseries")
    temp = channel(ts, "supply_temperature")["values"][120:540]
    assert len({v for v in temp if v is not None}) == 1  # frozen reading repeats exactly

    records, _ = engine.generate(seed=5, events=4, domains=["plc"], scenario="comms_dropout")
    ts = next(r for r in records if r["record_type"] == "timeseries")
    flow = channel(ts, "supply_flow")
    assert flow["values"][300:350] == [None] * 50 and flow["quality"][300] == "missing"


def test_documents_reference_real_records():
    records, manifest = engine.generate(seed=2, events=30)
    ids = {r["record_id"] for r in records if r["record_type"] == "document"}
    for e in manifest["events"]:
        assert set(e["relevant_documents"]) <= ids
    for r in records:
        if r["record_type"] == "document" and "superseded_by" in r:
            assert r["superseded_by"] in ids and r["status"] == "superseded"


def test_new_field_needs_no_code_change(tmp_path):
    """A made-up field defined only by a config file must just work."""
    (tmp_path / "scn").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "scn" / "hydraulics.json").write_text(json.dumps({
        "domain": "hydraulics",
        "assets": [{"id": "HPU-9"}],
        "configuration": {"setpoint_bar": {"min": 150, "max": 200}},
        "window": {"duration_s": 1.0, "pre_fault_s": 0.5},
        "channels": [{"name": "line_pressure", "unit": "bar", "sample_rate_hz": 100,
                      "baseline": [{"type": "constant", "value": {"ref": "setpoint_bar"}},
                                   {"type": "noise", "sigma": 0.5}]}],
        "scenarios": [{"id": "hose_burst",
                       "effects": [{"channel": "line_pressure", "type": "exp_decay", "tau_s": 0.05}],
                       "events": [{"offset_s": 0.1, "name": "PRESSURE_LOW", "state_to": True, "severity": "trip"}]}],
    }))
    records, manifest = engine.generate(seed=1, events=3, scenario_dir=tmp_path / "scn",
                                        document_dir=tmp_path / "docs")
    assert manifest["events"][0]["domain"] == "hydraulics"
    assert all(not errors(r) for r in records)


def test_engine_source_names_no_field():
    """The engine must not mention any engineering field or signal by name."""
    src = (ROOT / "generator" / "engine.py").read_text().lower()
    for word in ("cavity", "klystron", "vacuum", "pump", "bearing", "valve", "plc", "interlock rack"):
        assert not re.search(rf"\b{word}\b", src), word
