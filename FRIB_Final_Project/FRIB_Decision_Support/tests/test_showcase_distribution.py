"""The offline presentation reports source evidence without executing it."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_l1_l2_showcase.py"
spec = importlib.util.spec_from_file_location("build_l1_l2_showcase", SCRIPT)
showcase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(showcase)


def make_evidence(tmp_path, scenarios=None):
    directory = tmp_path / "evidence"
    directory.mkdir()
    payload = {"schema_version": "1.0", "generated_at": "2026-10-11T12:00:00Z", "project": "FRIB", "summary": {"total": 2, "passed": 1, "failed": 1}, "scenarios": scenarios or [
        {"id": "pass-case", "title": "Original bytes preserved", "stage": "L1", "features": ["source preservation"], "status": "passed", "expected": {"unchanged": True}, "observed": {"unchanged": True}, "steps": ["Scope: API TestClient"], "input_files": [], "artifacts": []},
        {"id": "fail-case", "title": "Deliberate evidence failure", "stage": "L2", "features": ["quality reporting"], "status": "failed", "expected": "accepted", "observed": {"error": "Rejected input"}, "steps": ["Scope: deterministic helper"], "input_files": [], "artifacts": []},
    ]}
    (directory / "scenario_results.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def embedded(path):
    text = path.read_text(encoding="utf-8")
    data = re.search(r'<script id="showcase-data" type="application/json">(.*?)</script>', text, re.S).group(1)
    return text, json.loads(data)


def test_offline_showcase_uses_real_pass_failure_and_full_suite_counts(tmp_path):
    evidence = make_evidence(tmp_path)
    junit = evidence / "pytest-results.xml"
    junit.write_text('<testsuites><testsuite tests="999"><testcase classname="tests.test_quality_ui" name="quality_ui"/><testcase classname="tests.test_rag_service" name="rag"/><testcase classname="tests.test_units" name="bad"><failure>Expected error details</failure></testcase><testcase classname="tests.test_review_gate" name="skip"><skipped/></testcase></testsuite></testsuites>', encoding="utf-8")
    output = tmp_path / "Feature_Showcase.html"
    result = showcase.build_showcase(evidence, junit, output)
    text, data = embedded(output)
    assert result == data
    assert data["evidence"]["summary"] == {"total": 2, "passed": 1, "failed": 1, "other": 0}
    assert data["junit"]["summary"] == {"total": 4, "passed": 2, "failed": 1, "skipped": 1, "focused": 2}
    assert data["junit"]["tests"][1]["focused"] is False
    assert "Full JUnit suite · all four levels" in text
    assert "Scope: deterministic helper" in text and "API TestClient" in text
    assert len(re.findall(r'<section class="section', text)) == 12
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://', text)
    assert "fetch(" not in text
    assert data["evidence"]["source"]["url"] == "evidence/scenario_results.json"


def test_missing_evidence_and_junit_are_unavailable_not_passing(tmp_path):
    output = tmp_path / "showcase.html"
    result = showcase.build_showcase(tmp_path / "missing", None, output)
    assert result["evidence"]["available"] is False
    assert result["junit"]["available"] is False
    assert result["evidence"]["summary"]["passed"] == 0
    assert "unavailable" in " ".join(result["evidence"]["warnings"]).lower()
    assert "not inferred" in result["junit"]["warning"]


def test_evidence_cannot_inject_html_or_escape_source_directory(tmp_path):
    attack = '</script><img src=x onerror="alert(1)"><script>'
    evidence = make_evidence(tmp_path, [{"id": "safe-case", "title": attack, "stage": "L1", "features": [attack], "status": "failed", "expected": attack, "observed": {"error": attack}, "steps": ["Scope: API TestClient"], "input_files": ["../private.txt", "https://bad.invalid/collect", "C:\\private.txt"], "artifacts": []}])
    (tmp_path / "private.txt").write_text("private", encoding="utf-8")
    output = tmp_path / "showcase.html"
    result = showcase.build_showcase(evidence, None, output)
    text, data = embedded(output)
    assert attack not in text
    assert data["evidence"]["scenarios"][0]["title"] == attack
    assert data["evidence"]["scenarios"][0]["files"] == []
    assert len([warning for warning in result["evidence"]["warnings"] if "unsafe" in warning]) == 3
    assert "innerHTML" not in text


def test_plots_use_observed_artifact_values_units_and_marker_only_reduction(tmp_path):
    evidence = make_evidence(tmp_path)
    artifacts = evidence / "artifacts"
    artifacts.mkdir()
    event = {"event_id": "EVENT-1", "metadata": {"import_summary": {"time_basis": "row_index"}}, "signals": [
        {"name": "pressure", "unit": "Pa", "timestamps_s": list(range(3000)), "values": [2000.0] * 3000},
        {"name": "temperature", "unit": "K", "timestamps_s": [0, 1], "values": [290.0, 291.0]},
    ], "states": [{"name": "mode", "timestamp_s": 1, "value": "RUN"}], "logs": [{"timestamp_s": 1, "message": "Recorded evidence", "level": "INFO"}]}
    (artifacts / "case-event.json").write_text(json.dumps(event), encoding="utf-8")
    path = evidence / "scenario_results.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scenarios"][0]["artifacts"] = ["artifacts/case-event.json"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = showcase.build_showcase(evidence, None, tmp_path / "showcase.html")
    plot = result["evidence"]["plots"][0]
    pressure, temperature = plot["channels"]
    assert pressure["unit"] == "Pa" and temperature["unit"] == "K"
    assert pressure["reduced"] is True and pressure["observed_count"] == 3000
    assert pressure["display_count"] <= 1401
    assert set(pressure["values"]) == {2000.0}
    assert pressure["times"][0] == 0 and pressure["times"][-1] == 2999
    assert pressure["time_label"] == "Record order (not measured time)"
    assert plot["state_count"] == 1 and plot["log_count"] == 1


def test_runner_summary_mismatch_is_flagged_and_unknown_status_is_not_passed(tmp_path):
    evidence = make_evidence(tmp_path, [{"id": "pending", "status": "unknown", "steps": [], "features": [], "input_files": [], "artifacts": []}])
    result = showcase.build_showcase(evidence, None, tmp_path / "showcase.html")
    assert result["evidence"]["summary"] == {"total": 1, "passed": 0, "failed": 0, "other": 1}
    assert any("summary differs" in warning for warning in result["evidence"]["warnings"])


def test_embedded_offline_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional; syntax check runs when the runtime is available")
    scripts = re.findall(r"<script>(.*?)</script>", showcase.HTML, re.S)
    assert len(scripts) == 1
    result = subprocess.run([node, "--check"], input=scripts[0], text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
