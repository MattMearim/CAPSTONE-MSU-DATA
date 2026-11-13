"""Troubleshooting regressions exercise only disposable API storage."""
import hashlib
import json

import pytest

from frib_ds.models import EngineeringEvent
from test_mixed_api import environment


def test_database_only_legacy_capture_can_be_drafted_without_claiming_original_bytes(environment):
    client, state, _ = environment
    event = EngineeringEvent(event_id="LEGACY-DB", domain="other", event_type="evidence_record",
        provenance={"source": "legacy_database_import"}, metadata={"operator_note": "Original file unavailable"},
        logs=[{"timestamp_s": 0, "message": "Legacy capture retained in the database"}])
    state["services"].repo.save_event(event)
    assert not state["services"].files.original(event.event_id).exists()
    assert client.get("/events/LEGACY-DB/download").status_code == 200
    assert client.post("/events/LEGACY-DB/analyze").status_code == 200
    drafted = client.post("/events/LEGACY-DB/draft")
    assert drafted.status_code == 200, drafted.text
    snapshot = drafted.json()["evidence_snapshot"]
    assert snapshot["event_sha256_scope"] == "canonical_event_model"
    assert snapshot["event_sha256"] == hashlib.sha256(event.model_dump_json(indent=2).encode("utf-8")).hexdigest()
    assert not state["services"].files.original(event.event_id).exists()
    draft_id = drafted.json()["draft_id"]
    reviewed = client.post(f"/drafts/{draft_id}/review", json={"decision": "escalate", "reviewer": "Regression test"})
    assert reviewed.status_code == 200
    assert client.get("/knowledge").json() == []


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("location", ["event", "signal", "state", "log"])
def test_nonfinite_nested_metadata_rejected_atomically(environment, nonfinite, location):
    client, state, _ = environment
    payload = {"event_id": "INVALID-METADATA", "domain": "other", "event_type": "evidence_record",
        "provenance": {"source": "uploaded_json"},
        "signals": [{"name": "voltage", "unit": "V", "sample_rate_hz": 1,
            "timestamps_s": [0, 1], "values": [1, 2]}],
        "states": [{"name": "permit", "value": "ON", "timestamp_s": 0}],
        "logs": [{"timestamp_s": 0, "message": "Capture received"}]}
    metadata = {"nested": [{"measurement": nonfinite}]}
    if location == "event":
        payload["metadata"] = metadata
    else:
        payload[{"signal": "signals", "state": "states", "log": "logs"}[location]][0]["metadata"] = metadata
    # Python's decoder accepts these nonstandard JSON tokens; the API must not
    # silently turn them into null during Pydantic JSON persistence.
    response = client.post("/events", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 400, response.text
    assert "finite" in response.json()["detail"].lower()
    assert state["services"].repo.list_events() == []
    assert list(state["services"].files.event_dir.iterdir()) == []
    assert client.get("/audit").json() == []


@pytest.mark.parametrize("route", ["quality", "preview", "import"])
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_import_options_cannot_preview_or_persist_as_null(environment, route, token):
    client, state, _ = environment
    options = '{"event_id":"BAD-OPTIONS","metadata":{"nested":{"value":' + token + '}}}'
    response = client.post(f"/ingestion/{route}",
        files={"file": ("capture.tsv", b"time [s]\tvoltage [V]\n0\t1\n1\t2\n")},
        data={"options": options, "validate": "true"})
    assert response.status_code == 400, response.text
    assert "finite" in response.json()["detail"].lower()
    assert state["services"].repo.list_events() == []
    assert list(state["services"].files.event_dir.iterdir()) == []
    assert client.get("/audit").json() == []


def test_explicit_missing_notes_and_finite_metadata_are_retained(environment):
    client, _, _ = environment
    metadata = {"observed_text": "NaN", "missing": None, "bounds": [0, 1e308]}
    payload = {"event_id": "VALID-METADATA", "domain": "other", "event_type": "evidence_record",
        "provenance": {"source": "uploaded_json"}, "metadata": metadata}
    response = client.post("/events", json=payload)
    assert response.status_code == 200, response.text
    assert client.get("/events/VALID-METADATA/download").json()["metadata"] == metadata
