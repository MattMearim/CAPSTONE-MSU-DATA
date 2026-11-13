"""Exercise all four levels and reset using isolated, disposable application data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "system_verification")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    started = time.monotonic()
    env_keys = ("FRIB_CONFIG_DIR", "FRIB_DATA_DIR", "FRIB_LLM_PROVIDER", "FRIB_EMBEDDING_PROVIDER", "FRIB_VECTOR_PROVIDER")
    previous = {key: os.environ.get(key) for key in env_keys}
    failure = None

    def check(name, action):
        begin = time.monotonic()
        try:
            observation = action()
        except Exception as exc:
            results.append({"name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            raise
        results.append({"name": name, "status": "passed", "observed": observation,
                        "duration_s": round(time.monotonic() - begin, 3)})
        print(f"PASS {name}", flush=True)
        return observation

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    try:
        with tempfile.TemporaryDirectory(prefix="frib-system-", dir=output) as temporary:
            os.environ.update(FRIB_CONFIG_DIR=str(PROJECT / "config"), FRIB_DATA_DIR=str(Path(temporary) / "data"),
                              FRIB_LLM_PROVIDER="mock", FRIB_EMBEDDING_PROVIDER="hash", FRIB_VECTOR_PROVIDER="sqlite")
            from fastapi.testclient import TestClient
            from frib_ds.api.main import app
            from frib_ds.bootstrap import get_services
            from frib_ds.config import get_config
            get_services.cache_clear()
            get_config.cache_clear()
            with TestClient(app) as client:
                def request(method, path, expected=200, **kwargs):
                    response = client.request(method, path, **kwargs)
                    require(response.status_code == expected,
                            f"{method} {path}: expected HTTP {expected}, received {response.status_code}: {response.text[:800]}")
                    return response

                def post(path, **kwargs):
                    return request("POST", path, **kwargs).json()

                def counts():
                    return request("GET", "/system/data").json()["counts"]

                def empty():
                    current = counts()
                    require(all(value == 0 for key, value in current.items() if key != "audit_entries"), current)
                    for path in ("/events", "/documents", "/knowledge"):
                        require(request("GET", path).json() == [], path + " is not empty")
                    response = post("/rag/query", json={"question": "RF tuner pressure trip procedure"})
                    require(response["sources"] == [] and response["mode"] == "insufficient_context", response)
                    return current

                check("Fresh isolated application is empty and healthy", lambda: {
                    "health": request("GET", "/health").json(), "counts": empty()})

                def units():
                    response = post("/units/convert", json={"value": 1000, "from_unit": "mbar", "to_unit": "Pa"})
                    require(response["converted_value"] == 100000, response)
                    request("POST", "/units/convert", expected=400,
                            json={"value": 1, "from_unit": "V", "to_unit": "W"})
                    return response
                check("Unit conversion and incompatible dimensions", units)

                contents = (b"time [s],pressure [kPa],mode,note\n"
                            b"0,1,READY,start\n1,20 mbar,RUN,review\n2,1,RUN,steady\n")
                settings = {"event_id": "SMOKE-MIXED", "domain": "other",
                            "column_roles": {"pressure [kPa]": "numeric", "mode": "category", "note": "log"}}

                def mixed():
                    result = post("/ingestion/import", files={"file": ("mixed.csv", contents)},
                                  data={"options": json.dumps(settings)})
                    event = result["event"]
                    require(event["signals"][0]["unit"] == "Pa", event["signals"])
                    require(event["signals"][0]["values"] == [1000, 2000, 1000], event["signals"])
                    require(bool(event["states"]) and len(event["logs"]) == 3, "Mixed evidence was lost")
                    original = result["original_file"]
                    require(request("GET", f'/events/SMOKE-MIXED/files/{original["file_id"]}/download').content == contents,
                            "Original source bytes changed")
                    csv = request("GET", "/events/SMOKE-MIXED/download?format=csv").text
                    require("Pa" in csv and "log" in csv and "state" in csv, "Export lacks units or mixed records")
                    return {"unit": "Pa", "values": [1000, 2000, 1000], "original_sha256": hashlib.sha256(contents).hexdigest()}
                check("L1 mixed evidence, uniform units and original/CSV downloads", mixed)

                def corruption():
                    damaged = b"time [s],voltage [V]\n0,1\n1,2,broken\n2,3\n"
                    report = post("/ingestion/quality", files={"file": ("damaged.csv", damaged)})
                    require(report["status"] == "blocked", report)
                    request("POST", "/ingestion/import", expected=400, files={"file": ("damaged.csv", damaged)})
                    result = post("/ingestion/import", files={"file": ("damaged.csv", damaged)},
                                  data={"options": json.dumps({"event_id": "SMOKE-REPAIRED",
                                        "_repairs": [{"operation": "drop_malformed_rows", "rows": [3]}]})})
                    require(bool(result["repair_receipt"]) and bool(result["derived_file"]), result)
                    require(result["original_file"]["checksum"] == hashlib.sha256(damaged).hexdigest(), "Lost original checksum")
                    return {"blocked_before_review": True, "explicit_repair": result["repair_receipt"]}
                check("L1 corruption flags, rejection and explicit repair receipt", corruption)

                text = b"RF tuner pressure trip reflected power procedure. Review the captured RF evidence before assigning a cause.\n"
                document = check("L3 approved procedure upload and original download", lambda: post(
                    "/documents/index", files={"file": ("rf.md", text)},
                    data={"approved": "true", "title": "RF tuner pressure trip procedure", "version": "smoke-1"}))
                require(request("GET", f'/documents/{document["document_id"]}/download').content == text,
                        "Procedure original differs")
                unapproved = post("/documents/index", files={"file": ("private.md", text)}, data={"approved": "false"})

                event_ids = []
                for domain in ("rf", "mechanical", "plc"):
                    def generated(domain=domain):
                        event = post("/events/generate", json={"domain": domain, "seed": 42})
                        event_ids.append(event["event_id"])
                        result = post(f'/events/{event["event_id"]}/analyze')
                        require(bool(result["features"]) and bool(result["plot_specs"]), result)
                        require(all(plot.get("title") for plot in result["plot_specs"]), "An analysis plot lacks a title")
                        for plot in result["plot_specs"]:
                            if plot.get("kind") == "timeseries":
                                require(all(plot.get("units", {}).get(name) for name in plot["signals"]),
                                        "A time-series plot lacks a channel unit")
                        require(request("GET", f'/events/{event["event_id"]}/analysis').json() == result,
                                "Saved analysis differs")
                        return {"event_id": event["event_id"], "processor": result["processor"],
                                "plot_count": len(result["plot_specs"])}
                    check(f"L2 {domain} generation, analysis, labeled plot specifications and persistence", generated)

                def rag():
                    result = post("/rag/query", json={"question": "RF tuner pressure trip reflected power procedure"})
                    require(result["grounded"] and bool(result["sources"]), result)
                    require({source["document_id"] for source in result["sources"]} == {document["document_id"]}, result)
                    require(all(source["document_id"] != unapproved["document_id"] for source in result["sources"]), result)
                    event_result = post("/rag/query", json={"question": "RF tuner pressure trip procedure", "event_id": event_ids[0]})
                    require(bool(event_result["evidence"]), "Event response lost derived evidence")
                    return {"mode": result["mode"], "approved_sources": len(result["sources"]),
                            "event_evidence_count": len(event_result["evidence"])}
                check("L3 retrieval citations, approval exclusion and measured evidence", rag)

                def review():
                    draft = post(f"/events/{event_ids[0]}/draft")
                    require(draft["status"] == "draft" and request("GET", "/knowledge").json() == [],
                            "Draft bypassed human review")
                    result = post(f'/drafts/{draft["draft_id"]}/review', json={"decision": "approve",
                                  "reviewer": "Synthetic smoke reviewer", "comments": "Verified test evidence"})
                    require(bool(result["knowledge"]), result)
                    require(len(request("GET", "/knowledge").json()) == 1, "Approved knowledge missing")
                    require(bool(request("GET", "/knowledge/search?q=rf").json()), "Knowledge search failed")
                    request("POST", f'/drafts/{draft["draft_id"]}/review', expected=400,
                            json={"decision": "approve", "reviewer": "Synthetic smoke reviewer"})
                    return {"draft_id": draft["draft_id"], "status": "approved", "duplicate_review_rejected": True}
                check("L4 draft gate, human approval, knowledge search and duplicate-review rejection", review)

                def reset_guard():
                    before = counts()
                    response = client.post("/system/reset", json={"confirmation": "wrong"})
                    require(response.status_code in (400, 422), response.text)
                    require(counts() == before, "Rejected reset changed stored data")
                    return {"rejected_status": response.status_code, "unchanged": True, "counts": before}
                check("Reset confirmation guard preserves populated data", reset_guard)

                reset = check("Reset removes originals, derived records and retrieval vectors", lambda: post(
                    "/system/reset", json={"confirmation": "RESET"}))
                require(reset["reset"] is True and reset["removed"]["events"] >= 5, reset)
                check("Deleted records/downloads return 404 and retrieval is empty", lambda: {
                    "event_status": request("GET", f"/events/{event_ids[0]}", expected=404).status_code,
                    "document_status": request("GET", f'/documents/{document["document_id"]}/download', expected=404).status_code,
                    "counts": empty()})
                require(counts()["audit_entries"] == 1, "Reset receipt missing or old audit content remains")
                get_services.cache_clear()
                get_services()
                check("Restart preserves the empty reset state", empty)

                def reuse():
                    result = post("/documents/index", files={"file": ("rf.md", text)}, data={"approved": "true"})
                    event = post("/events/generate", json={"domain": "rf", "seed": 17})
                    post(f'/events/{event["event_id"]}/analyze')
                    draft = post(f'/events/{event["event_id"]}/draft')
                    approved = post(f'/drafts/{draft["draft_id"]}/review', json={"decision": "approve", "reviewer": "Smoke reviewer"})
                    require(bool(approved["knowledge"]), "Post-reset review failed")
                    return {"new_document": result["document_id"], "new_event": event["event_id"], "human_review": "approved"}
                check("All four levels accept new work after reset", reuse)
                check("Repeated reset finishes empty", lambda: {
                    "reset": post("/system/reset", json={"confirmation": "RESET"})["reset"], "counts": empty()})
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        print(f"FAIL {failure}", flush=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if "get_services" in locals():
            get_services.cache_clear()
            get_config.cache_clear()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "scope": "isolated mock/hash/sqlite API lifecycle",
              "user_data_touched": False, "status": "failed" if failure else "passed", "error": failure,
              "duration_s": round(time.monotonic() - started, 3), "checks": results}
    (output / "system-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Full-system smoke checks", "", f"Status: **{report['status']}**. {len(results)} named checks.", "",
             "Disposable synthetic data; mock answers, hash embeddings and SQLite storage. No saved user data was touched.", ""]
    lines.extend(f"- {row['status'].upper()}: {row['name']}" for row in results)
    if failure:
        lines.extend(["", f"Failure: {failure}"])
    (output / "SYSTEM_SMOKE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {output / 'system-smoke.json'}", flush=True)
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
