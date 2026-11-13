"""Verify the fictional Test Lab through real APIs in disposable local storage.

Uses deterministic mock answers, hash retrieval and SQLite. Never connects to a
running server, resets the project, seeds saved data or modifies the fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ("FRIB_CONFIG_DIR", "FRIB_DATA_DIR", "FRIB_LLM_PROVIDER", "FRIB_EMBEDDING_PROVIDER", "FRIB_VECTOR_PROVIDER")


def require(condition, message):
    if not condition:
        raise AssertionError(str(message))


def close_number(actual, expected, tolerance=1e-6):
    if isinstance(expected, bool) or isinstance(expected, str) or expected is None:
        return actual == expected
    return isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - expected) <= tolerance


def fixture_path(manifest_path, entry):
    root = manifest_path.resolve().parents[2]
    path = (root / entry["path"]).resolve()
    require(path.is_relative_to(root), "Fixture paths must stay inside their project-shaped pack.")
    return path


def run_lab(manifest_path=PROJECT / "sample_data/test_lab/manifest.json", output=PROJECT / "test_lab_results"):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("fictional") is True and manifest.get("schema_version") == "1.0", "Unsupported or unmarked fixture manifest.")
    started = time.monotonic()
    checks, documents, captures, analyses = [], {}, {}, {}
    artifacts = output / "artifacts"
    artifacts.mkdir(exist_ok=True)
    saved_environment = {key: os.environ.get(key) for key in ENVIRONMENT}
    get_config = get_services = None

    def record(check_id, title, action, expected):
        begin = time.monotonic()
        try:
            observed = action()
            row = {"id": check_id, "title": title, "status": "passed", "expected": expected, "observed": observed}
        except Exception as exc:
            row = {"id": check_id, "title": title, "status": "failed", "expected": expected,
                   "error": f"{type(exc).__name__}: {exc}"}
        row["duration_s"] = round(time.monotonic() - begin, 3)
        checks.append(row)
        print(f"{row['status'].upper()} {check_id}: {title}", flush=True)

    def save_artifact(name, payload):
        path = artifacts / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return str(path.relative_to(output)).replace("\\", "/")

    try:
        with tempfile.TemporaryDirectory(prefix="frib-test-lab-") as temporary:
            workspace = Path(temporary)
            configuration = workspace / "config"
            configuration.mkdir()
            import yaml
            for name in ("app", "models", "rag", "processing", "domains"):
                value = yaml.safe_load((PROJECT / "config" / f"{name}.yaml").read_text(encoding="utf-8")) or {}
                if name == "app":
                    value.setdefault("app", {})["prompts_dir"] = str(PROJECT / "prompts")
                elif name == "models":
                    value = {"llm": {"provider": "mock"}, "embeddings": {"provider": "hash", "dimensions": 384},
                             "vector_store": {"provider": "sqlite"}}
                (configuration / f"{name}.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")
            os.environ.update(FRIB_CONFIG_DIR=str(configuration), FRIB_DATA_DIR=str(workspace / "data"),
                              FRIB_LLM_PROVIDER="mock", FRIB_EMBEDDING_PROVIDER="hash", FRIB_VECTOR_PROVIDER="sqlite")
            from fastapi.testclient import TestClient
            from frib_ds.api.main import app
            from frib_ds.bootstrap import get_services
            from frib_ds.config import get_config
            get_services.cache_clear()
            get_config.cache_clear()
            with TestClient(app) as client:
                def request(method, path, expected_status=200, **kwargs):
                    result = client.request(method, path, **kwargs)
                    require(result.status_code == expected_status, f"{method} {path} expected {expected_status}, got {result.status_code}: {result.text[:1400]}")
                    return result

                def upload(entry, endpoint, settings=None, validate=False):
                    payload = fixture_path(manifest_path, entry).read_bytes()
                    form = {"options": json.dumps(settings if settings is not None else entry["options"])}
                    if validate:
                        form["validate"] = "true"
                    return request("POST", endpoint, files={"file": (entry["filename"], payload, "application/octet-stream")}, data=form).json()

                def counts():
                    return request("GET", "/system/data").json()["counts"]

                def fresh():
                    state = counts()
                    require(all(value == 0 for value in state.values()), state)
                    result = request("POST", "/rag/query", json={"question": "RF cavity trip evidence review"}).json()
                    require(result["sources"] == [] and result["mode"] == "insufficient_context", result)
                    require(request("GET", "/health").json()["llm_provider"] == "mock", "Unexpected AI provider")
                    return {"counts": state, "empty_retrieval_mode": result["mode"], "user_data_touched": False}
                record("LAB-EMPTY", "Fresh isolated store and insufficient-context response", fresh, "No saved records and no false grounding.")

                for entry in manifest["procedures"]:
                    def index(entry=entry):
                        contents = fixture_path(manifest_path, entry).read_bytes()
                        require(hashlib.sha256(contents).hexdigest() == entry["sha256"], "Procedure fixture checksum mismatch")
                        result = request("POST", "/documents/index", files={"file": (entry["filename"], contents)},
                                         data={"approved": str(entry["approved"]).lower(), "title": entry["title"], "version": entry["version"]}).json()
                        documents[entry["id"]] = result
                        require(result["approved"] == entry["approved"] and result["version"] == entry["version"], result)
                        require((result["indexed_chunks"] > 0) == entry["approved"], result)
                        require(request("GET", f"/documents/{result['document_id']}/download").content == contents, "Procedure original differs")
                        return {"document": result, "original_verified": True}
                    record("DOC-" + entry["id"], entry["title"] + " / " + entry["version"], index,
                           "Exact original, explicit approval, version and approved-only indexing.")

                for entry in manifest["datasets"]:
                    def dataset(entry=entry):
                        contents = fixture_path(manifest_path, entry).read_bytes()
                        require(hashlib.sha256(contents).hexdigest() == entry["sha256"], "Dataset fixture checksum mismatch")
                        expected = entry["expected"]
                        before = counts()
                        original_file = None
                        preview = None
                        if entry["import_kind"] == "event":
                            native = json.loads(contents)
                            request("POST", "/events", json=native)
                            event = request("GET", f"/events/{native['event_id']}").json()
                            original_native = request("GET", f"/events/{native['event_id']}/download?format=json").json()
                            from frib_ds.models import EngineeringEvent
                            require(original_native == EngineeringEvent.model_validate(native).model_dump(mode="json"), "Native JSON original event content changed after contract validation")
                            source = request("POST", f"/events/{native['event_id']}/files", files={"file": (entry["filename"], contents)}).json()
                            original_file = source
                        else:
                            preview = upload(entry, "/ingestion/preview", validate=True)
                            require(counts() == before, "Preview wrote application records")
                            require(preview["validation"]["valid"] == expected["valid"], preview.get("validation"))
                            raw_codes = {issue["code"] for issue in preview["quality"]["original_l1"]["issues"]}
                            require(set(entry["expected_issue_codes"]).issubset(raw_codes), {"expected": entry["expected_issue_codes"], "actual": sorted(raw_codes)})
                            if not expected["valid"]:
                                request("POST", "/ingestion/import", expected_status=400, files={"file": (entry["filename"], contents)}, data={"options": json.dumps(entry["options"])})
                                require(counts() == before, "Rejected import changed application records")
                                if not expected.get("repaired_valid"):
                                    return {"blocked": True, "issue_codes": sorted(raw_codes), "errors": preview["validation"]["errors"], "no_writes": True}
                                repaired_options = {**entry["options"], **expected["repair_options"]}
                                preview = upload(entry, "/ingestion/preview", repaired_options, validate=True)
                                require(preview["validation"]["valid"] is True, preview)
                                require(counts() == before, "Repaired preview wrote application records")
                                imported = upload(entry, "/ingestion/import", repaired_options)
                                require(imported["repair_receipt"] and imported["derived_file"], "Repair copy or receipt missing")
                                derived = imported["derived_file"]
                                reviewed = request("GET", f"/events/{imported['event']['event_id']}/files/{derived['file_id']}/download").content.decode("utf-8")
                                require("keep invalid text" in reviewed and "keep missing" in reviewed, "Repair removed unrelated narrative evidence")
                                require("broken" not in reviewed and "NA" not in reviewed, "Explicit numeric-cell repair not applied")
                            else:
                                imported = upload(entry, "/ingestion/import")
                            event = imported["event"]
                            original_file = imported["original_file"]
                            save_artifact(entry["id"] + "-preview", preview)
                        event_id = event["event_id"]
                        captures[entry["id"]] = event
                        require(request("GET", f"/events/{event_id}/files/{original_file['file_id']}/download").content == contents, "Original source bytes changed")
                        original_file["source_sha256"] = hashlib.sha256(contents).hexdigest()
                        request("POST", "/events", expected_status=409, json=event)
                        signals = {signal["name"]: signal for signal in event["signals"]}
                        if "signals" in expected:
                            require(len(signals) == expected["signals"], "Measurement channel count differs")
                        for name, unit in expected.get("units", {}).items():
                            require(signals[name]["unit"] == unit, {name: signals[name]["unit"]})
                        for name, values in {**expected.get("values", {}), **expected.get("repaired_values", {})}.items():
                            require(len(signals[name]["values"]) == len(values) and all(close_number(a, b) for a, b in zip(signals[name]["values"], values)), {name: signals[name]["values"]})
                        for name, value in expected.get("first_values", {}).items():
                            require(close_number(signals[name]["values"][0], value), {name: signals[name]["values"][0]})
                        if "logs" in expected:
                            require(len(event["logs"]) == expected["logs"], "Source log count differs")
                        require(set(expected.get("state_channels", [])).issubset({state["name"] for state in event["states"]}), "Category/boolean records lost")
                        require(set(expected.get("log_levels", [])).issubset({log["level"] for log in event["logs"]}), "Severity labels lost")
                        if expected.get("pdf_pages"):
                            require(all(log["metadata"].get("source_page") == 1 for log in event["logs"]), "PDF page provenance lost")
                        request("POST", f"/events/{event_id}/draft", expected_status=400)
                        analysis = request("POST", f"/events/{event_id}/analyze").json()
                        analyses[entry["id"]] = analysis
                        require(analysis["processor"] == expected["processor"], analysis["processor"])
                        require(bool(analysis["findings"]) and bool(analysis["plot_specs"]), "Analysis evidence/plots missing")
                        for name, value in expected.get("features", {}).items():
                            require(close_number(analysis["features"].get(name), value, expected.get("feature_tolerance", 1e-6)), {name: analysis["features"].get(name), "expected": value})
                        if "sequence" in expected:
                            require(analysis["features"]["sequence"] == expected["sequence"], analysis["features"]["sequence"])
                        if "time_basis" in expected:
                            require(analysis["features"].get("time_basis") == expected["time_basis"], "Record order lost")
                        l2_codes = {issue["code"] for issue in analysis["features"]["data_quality"]["issues"]}
                        require(set(expected.get("l2_codes", [])).issubset(l2_codes), {"expected": expected.get("l2_codes"), "actual": sorted(l2_codes)})
                        require(request("GET", f"/events/{event_id}/analysis").json() == analysis, "Saved analysis differs")
                        for kind in ("json", "normalized-json", "csv"):
                            require(bool(request("GET", f"/events/{event_id}/download?format={kind}").content), "Export is empty")
                        return {"event_id": event_id, "processor": analysis["processor"], "channel_units": {name: signal["unit"] for name, signal in signals.items()},
                                "states": len(event["states"]), "logs": len(event["logs"]), "l2_codes": sorted(l2_codes),
                                "original_verified": True, "event_artifact": save_artifact(entry["id"] + "-event", event),
                                "analysis_artifact": save_artifact(entry["id"] + "-analysis", analysis)}
                    record("DATA-" + entry["id"], entry["title"], dataset, entry["expected_outcome"])

                def approval_exclusion():
                    result = request("POST", "/rag/query", json={"question": manifest["procedures"][0]["question"], "event_id": captures["RF-TRIP"]["event_id"]}).json()
                    allowed = {item["document_id"] for item in documents.values() if item["approved"]}
                    require(result["mode"] == "extractive" and result["grounded"] and result["sources"], result)
                    require(all(source["document_id"] in allowed for source in result["sources"]), "Unapproved source retrieved")
                    require("DRAFT-ONLY-CANARY" not in result["answer"], "Unapproved draft leaked into answer")
                    require(result["evidence"] == analyses["RF-TRIP"]["findings"], "Measured evidence not separated/preserved")
                    source_ids = {source["document_id"] for source in result["sources"]}
                    require(documents["RF-A"]["document_id"] in source_ids and documents["RF-B"]["document_id"] in source_ids, "Both approved revisions should be visible before retirement")
                    require(all(source.get("version") and source.get("excerpt") for source in result["sources"]), "Version/excerpt citation metadata missing")
                    return {"sources": result["sources"], "measured_evidence_count": len(result["evidence"]), "mode": result["mode"], "artifact": save_artifact("approved-retrieval", result)}
                record("RAG-APPROVAL", "Approved-only retrieval, visible revision metadata and measured evidence", approval_exclusion,
                       "Approved A and B may coexist; unapproved C is excluded, with no generated AI interpretation.")

                def retrieval_formats():
                    result = {}
                    for case_id, document_id in [("CRYO", "CRYO"), ("MECHANICAL", "MECHANICAL"), ("PLC", "PLC"), ("RF-XRAY", "RF-XRAY")]:
                        entry = next(item for item in manifest["datasets"] if item["id"] == case_id)
                        answer = request("POST", "/rag/query", json={"question": entry["question"], "event_id": captures[case_id]["event_id"]}).json()
                        require(documents[document_id]["document_id"] in {source["document_id"] for source in answer["sources"]}, {"case": case_id, "answer": answer})
                        if document_id == "CRYO":
                            require(any(source.get("page") == 1 for source in answer["sources"] if source["document_id"] == documents[document_id]["document_id"]), "PDF page citation missing")
                        result[case_id] = [{"title": source["title"], "version": source["version"], "page": source["page"]} for source in answer["sources"]]
                    return result
                record("RAG-FORMATS", "PDF, text and Markdown retrieval across engineering domains", retrieval_formats,
                       "Each relevant approved domain procedure can be retrieved; PDF source has page metadata.")

                for entry in manifest["datasets"]:
                    decision = entry["expected"].get("review")
                    if not decision:
                        continue
                    def human_review(entry=entry, decision=decision):
                        event_id = captures[entry["id"]]["event_id"]
                        before = request("GET", "/knowledge").json()
                        draft = request("POST", f"/events/{event_id}/draft", params={"question": entry["question"]}).json()
                        require(draft["status"] == "draft" and draft["generated_by"] == "deterministic_fallback", draft)
                        require(request("GET", "/knowledge").json() == before, "Draft bypassed human review")
                        require(draft["observations"] == analyses[entry["id"]]["findings"], "Draft changed actual measured findings")
                        require(all(item["support"] == "tentative_evidence_pattern" for item in draft["hypotheses"]), "Hypothesis certainty overstated")
                        payload = {"decision": decision, "reviewer": "Fictional named lab reviewer", "comments": "Training evidence reviewed; no operational authorization."}
                        if decision == "correct":
                            corrected = json.loads(json.dumps(draft))
                            corrected["summary"] = "Human-corrected fictional PLC summary: recorded transitions only; cause remains unconfirmed."
                            payload["corrected_draft"] = corrected
                        result = request("POST", f"/drafts/{draft['draft_id']}/review", json=payload).json()
                        expected_status = {"approve": "approved", "correct": "corrected", "escalate": "escalated"}[decision]
                        final = request("GET", f"/drafts/{draft['draft_id']}").json()
                        require(final["status"] == expected_status, final)
                        after = request("GET", "/knowledge").json()
                        require(len(after) - len(before) == (0 if decision == "escalate" else 1), "Incorrect knowledge publication outcome")
                        require(bool(result["knowledge"]) == (decision != "escalate"), result)
                        if decision == "correct":
                            require(result["knowledge"]["draft"]["summary"] == payload["corrected_draft"]["summary"], "Correction was not preserved")
                        request("POST", f"/drafts/{draft['draft_id']}/review", expected_status=400, json=payload)
                        return {"decision": decision, "status": final["status"], "knowledge_created": bool(result["knowledge"]), "draft_artifact": save_artifact(entry["id"] + "-draft", final)}
                    record("REVIEW-" + entry["id"], "Human " + decision + " / " + entry["title"], human_review,
                           "Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.")

                def revision_retirement():
                    old_id = documents["RF-A"]["document_id"]
                    request("DELETE", f"/documents/{old_id}")
                    request("GET", f"/documents/{old_id}/download", expected_status=404)
                    answer = request("POST", "/rag/query", json={"question": manifest["procedures"][0]["question"], "event_id": captures["RF-TRIP"]["event_id"]}).json()
                    require(old_id not in {source["document_id"] for source in answer["sources"]}, "Deleted revision remains retrievable")
                    require(documents["RF-B"]["document_id"] in {source["document_id"] for source in answer["sources"]}, "Current revision disappeared")
                    return {"retired_version": "LAB-A", "retained_version": "LAB-B", "source_versions": [source["version"] for source in answer["sources"]]}
                record("RAG-RETIRE", "Explicit revision retirement removes retrieval and original", revision_retirement,
                       "No automatic supersession is claimed; explicit deletion retires A and preserves B.")

                def attachment_lifecycle():
                    event_id = captures["PLC"]["event_id"]
                    payload = b"FICTIONAL supporting screenshot substitute; no real machine data.\n"
                    saved = request("POST", f"/events/{event_id}/files", files={"file": ("supporting_note.txt", payload)}).json()
                    require(request("GET", f"/events/{event_id}/files/{saved['file_id']}/download").content == payload, "Supporting attachment changed")
                    request("DELETE", f"/events/{event_id}/files/{saved['file_id']}")
                    request("GET", f"/events/{event_id}/files/{saved['file_id']}/download", expected_status=404)
                    require(bool(request("GET", f"/events/{event_id}/files").json()), "Deleting an attachment removed original file")
                    return {"supporting_file_removed": True, "original_retained": True}
                record("FILES", "Add, download and remove a supporting file", attachment_lifecycle,
                       "Selected file is removed; original evidence and event remain.")

                def restart():
                    before = counts()
                    get_services.cache_clear()
                    require(counts() == before, "Restart changed catalog counts")
                    for key, event in captures.items():
                        require(request("GET", f"/events/{event['event_id']}").json() == event, key + " changed after restart")
                        require(request("GET", f"/events/{event['event_id']}/analysis").json() == analyses[key], key + " analysis changed after restart")
                    require(bool(request("GET", "/knowledge/search?q=fictional").json()), "Reviewed knowledge search failed")
                    answer = request("POST", "/rag/query", json={"question": manifest["procedures"][0]["question"]}).json()
                    require(documents["RF-A"]["document_id"] not in {source["document_id"] for source in answer["sources"]}, "Retired procedure resurrected after restart")
                    return {"counts": before, "events_and_analyses_unchanged": len(captures), "knowledge_search": True}
                record("RESTART", "Stored evidence, analyses, reviewed knowledge and retired revisions survive restart", restart,
                       "Persistent SQLite/vector state reproduces current records without resurrecting deleted revisions.")

                def cascade():
                    event_id = captures["RF-TRIP"]["event_id"]
                    original_files = request("GET", f"/events/{event_id}/files").json()
                    before = len(request("GET", "/knowledge").json())
                    request("DELETE", f"/events/{event_id}")
                    for suffix in ("", "/analysis", "/draft", "/files"):
                        request("GET", f"/events/{event_id}{suffix}", expected_status=404)
                    for item in original_files:
                        request("GET", f"/events/{event_id}/files/{item['file_id']}/download", expected_status=404)
                    require(len(request("GET", "/knowledge").json()) == before - 1, "Event's reviewed knowledge was not cascaded")
                    return {"deleted_event": event_id, "files_removed": len(original_files), "dependent_analysis_draft_knowledge_removed": True}
                record("DELETE", "Event deletion removes original files and dependent derived records", cascade,
                       "Deleting one test event cascades its files, analysis, draft, review and knowledge.")
    except Exception as exc:
        checks.append({"id": "RUNNER", "title": "Test lab setup/execution", "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if get_services is not None:
            get_services.cache_clear()
        if get_config is not None:
            get_config.cache_clear()
        for key, value in saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    passed = sum(row["status"] == "passed" for row in checks)
    report = {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path), "fictional": True, "user_data_touched": False,
        "scope": "Real local API lifecycle; mock LLM/hash embeddings/SQLite; temporary app storage removed at exit.",
        "limits": ["No live FRIB integration, operational approval or causal-accuracy validation.", "Mock retrieval is extractive; local AI providers are not tested.", "No OCR or PDF image/table interpretation.", "Approved revisions coexist until explicitly retired; no automatic supersession."],
        "duration_s": round(time.monotonic() - started, 3), "status": "passed" if passed == len(checks) else "failed",
        "summary": {"total": len(checks), "passed": passed, "failed": len(checks) - passed}, "checks": checks}
    (output / "test-lab-results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Fictional Test Lab execution", "", f"Status: **{report['status']}**. {passed}/{len(checks)} grouped checks passed.", "",
             report["scope"], "Saved project data was not touched. Run timestamps and generated record IDs vary; input fixtures and expected engineering values are deterministic.", ""]
    for row in checks:
        lines.extend([f"- **{row['status'].upper()} {row['id']}** - {row['title']}", f"  {row.get('error', row.get('expected', ''))}"])
    lines.extend(["", "Limits:"] + [f"- {limit}" for limit in report["limits"]])
    (output / "TEST_LAB_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT / "sample_data/test_lab/manifest.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "test_lab_results")
    args = parser.parse_args()
    report = run_lab(args.manifest, args.output)
    print(json.dumps(report["summary"]))
    print(f"Report: {args.output.resolve() / 'test-lab-results.json'}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
