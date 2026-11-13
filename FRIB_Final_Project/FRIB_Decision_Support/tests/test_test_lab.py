"""Test-pack contracts, reproducibility and real isolated system outcomes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

from pypdf import PdfReader

PROJECT = Path(__file__).resolve().parents[1]


def script(name):
    specification = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_pack_is_reproducible_and_every_original_matches_manifest(tmp_path):
    generator = script("generate_test_lab")
    first = generator.generate(tmp_path / "first")
    second = generator.generate(tmp_path / "second")
    assert first == second
    assert len(first["datasets"]) == 13 and len(first["procedures"]) == 7
    for entry in first["datasets"] + first["procedures"]:
        left = tmp_path / "first" / entry["path"]
        right = tmp_path / "second" / entry["path"]
        assert left.read_bytes() == right.read_bytes()
        assert left.stat().st_size == entry["size_bytes"]
        assert hashlib.sha256(left.read_bytes()).hexdigest() == entry["sha256"]


def test_manifest_supports_manual_use_without_implicit_approval_or_repairs():
    manifest = json.loads((PROJECT / "sample_data/test_lab/manifest.json").read_text(encoding="utf-8"))
    assert manifest["fictional"] is True
    assert {entry["import_kind"] for entry in manifest["datasets"]} == {"mixed", "event", "text"}
    assert {entry["format"] for entry in manifest["datasets"]} == {"csv", "tsv", "json", "log", "pdf"}
    assert len({entry["id"] for entry in manifest["datasets"]}) == len(manifest["datasets"])
    for entry in manifest["datasets"]:
        assert entry["expected_outcome"] and entry["question"] and entry["steps"]
        assert not entry["options"].get("_repairs")
        assert entry["options"]["metadata"]["fictional"] is True
        assert entry["options"]["metadata"]["beam_state"] == "SIMULATION"
    draft = next(entry for entry in manifest["procedures"] if entry["id"] == "RF-DRAFT")
    assert draft["approved"] is False
    assert {entry["version"] for entry in manifest["procedures"] if entry["id"] in {"RF-A", "RF-B"}} == {"LAB-A", "LAB-B"}


def test_shipped_pdfs_are_real_selectable_text_with_fictional_notice_and_page():
    paths = [PROJECT / "sample_docs/test_lab/cryo_review.pdf", PROJECT / "sample_data/test_lab/operator_note.pdf"]
    for path in paths:
        assert path.read_bytes().startswith(b"%PDF-")
        reader = PdfReader(path)
        assert len(reader.pages) == 1 and not reader.is_encrypted
        text = reader.pages[0].extract_text()
        assert "FICTIONAL TRAINING ONLY" in text
        assert "human" in text.lower() or "cause remains unconfirmed" in text.lower()


def test_native_json_has_distinct_measured_grids_and_no_ground_truth_shortcut():
    from frib_ds.models import EngineeringEvent
    source = json.loads((PROJECT / "sample_data/test_lab/mechanical.json").read_text(encoding="utf-8"))
    event = EngineeringEvent.model_validate(source)
    assert event.metadata["fictional"] is True
    assert "synthetic_ground_truth" not in event.metadata
    vibration, temperature = event.signals
    assert vibration.sample_rate_hz == 200 and len(vibration.values) == 401
    assert temperature.sample_rate_hz == 20 and len(temperature.values) == 41
    assert vibration.timestamps_s != temperature.timestamps_s
    assert vibration.timestamps_s[0] == temperature.timestamps_s[0] == 0
    assert vibration.timestamps_s[-1] == temperature.timestamps_s[-1] == 2


def test_full_pack_exercises_real_apis_in_isolation_and_restores_environment(tmp_path, monkeypatch):
    runner = script("run_test_lab")
    sentinel_data = tmp_path / "saved-user-data"
    sentinel_data.mkdir()
    sentinel = sentinel_data / "do-not-touch.txt"
    sentinel.write_text("Saved user content", encoding="utf-8")
    monkeypatch.setenv("FRIB_DATA_DIR", str(sentinel_data))
    monkeypatch.setenv("FRIB_LLM_PROVIDER", "offline-user-provider")
    previous = {key: os.environ.get(key) for key in runner.ENVIRONMENT}
    report = runner.run_lab(output=tmp_path / "evidence")
    failures = [entry for entry in report["checks"] if entry["status"] != "passed"]
    assert failures == [], failures
    assert report["summary"] == {"total": 32, "passed": 32, "failed": 0}
    assert report["user_data_touched"] is False
    assert sentinel.read_text(encoding="utf-8") == "Saved user content"
    assert list(sentinel_data.iterdir()) == [sentinel]
    assert {key: os.environ.get(key) for key in runner.ENVIRONMENT} == previous
    recorded = json.loads((tmp_path / "evidence/test-lab-results.json").read_text(encoding="utf-8"))
    assert recorded == report
    ids = {entry["id"] for entry in report["checks"]}
    assert {"RAG-APPROVAL", "RAG-FORMATS", "RAG-RETIRE", "REVIEW-RF-TRIP", "REVIEW-PLC", "REVIEW-RF-XRAY", "RESTART", "DELETE", "FILES"}.issubset(ids)


def test_runner_reports_modified_fixtures_as_failure_instead_of_success(tmp_path):
    generator, runner = script("generate_test_lab"), script("run_test_lab")
    pack = tmp_path / "pack"
    generator.generate(pack)
    original = pack / "sample_data/test_lab/incompatible_units.csv"
    original.write_bytes(original.read_bytes() + b"3,4 V\n")
    report = runner.run_lab(pack / "sample_data/test_lab/manifest.json", tmp_path / "results")
    assert report["status"] == "failed" and report["summary"]["failed"] == 1
    failed = next(entry for entry in report["checks"] if entry["id"] == "DATA-BAD-UNIT")
    assert failed["status"] == "failed" and "checksum mismatch" in failed["error"]
    assert report["summary"]["passed"] == 31
