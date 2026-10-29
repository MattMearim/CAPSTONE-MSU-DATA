"""Native TSV follows the same bounded, auditable tabular workflow as CSV."""
import hashlib
import json

import pytest

from frib_ds.ingestion import build_event, inspect_upload
from frib_ds.ingestion.quality import assess_upload, repair_upload
from frib_ds.storage.files import EventFileStore
from test_mixed_api import environment


RAW = (b"time [ms]\tpressure [kPa]\tmode\tmessage\r\n"
       b"0\t100\tOFF\t[INFO] capture started\r\n"
       b"10\t1.2 bar\tON\t[WARN] valve changed\r\n"
       b"20\t130\tON\t[ERROR] check sensor\r\n")


@pytest.mark.parametrize("filename", ["capture.tsv", "capture.TSV"])
def test_native_tsv_preview_build_and_quality_preserve_semantics(filename):
    preview = inspect_upload(filename, RAW)
    assert preview["format"] == "csv"  # Existing tabular role-mapping contract.
    assert preview["row_count"] == 3
    assert preview["suggested_time_unit"] == "ms"
    report = assess_upload(filename, RAW)
    assert report["status"] != "blocked", report
    assert "mixed_unit_scales" in {issue["code"] for issue in report["issues"]}
    event = build_event(filename, RAW)
    assert event.signals[0].name == "pressure"
    assert event.signals[0].unit == "kPa"
    assert event.signals[0].values == pytest.approx([100, 120, 130])
    assert event.signals[0].timestamps_s == pytest.approx([0, .01, .02])
    assert [(item.name, item.value) for item in event.states] == [("mode", "OFF"), ("mode", "ON")]
    assert [item.level for item in event.logs] == ["INFO", "WARNING", "ERROR"]
    assert event.metadata["source_filename"] == filename
    assert event.provenance.checksum == hashlib.sha256(RAW).hexdigest()


def test_tsv_repair_preserves_tabs_crlf_and_original_bytes(tmp_path):
    contents = b"time [s]\tvoltage [V]\r\n0\t1\r\n1\t2\textra\r\n2\t3\r\n"
    assert assess_upload("damaged.tsv", contents)["status"] == "blocked"
    repaired, receipt = repair_upload("damaged.tsv", contents, {}, [
        {"operation": "drop_malformed_rows", "rows": [3]}])
    assert repaired == b"time [s]\tvoltage [V]\r\n0\t1\r\n2\t3\r\n"
    assert receipt["before_checksum"] == hashlib.sha256(contents).hexdigest()
    assert receipt["after_checksum"] == hashlib.sha256(repaired).hexdigest()
    assert assess_upload("damaged.tsv", repaired)["status"] != "blocked"
    event = build_event("damaged.tsv", repaired, {"event_id": "TSV-REPAIR"})
    files = EventFileStore(tmp_path / "events")
    files.save(event)
    original = files.save_attachment(event.event_id, "damaged.tsv", contents)
    derived = files.save_attachment(event.event_id, "reviewed_copy.tsv", repaired)
    assert files.attachment_path(event.event_id, original["file_id"]).read_bytes() == contents
    assert files.attachment_path(event.event_id, derived["file_id"]).read_bytes() == repaired


def test_tsv_import_retains_original_and_reviewed_extensions(environment):
    client, state, _ = environment
    contents = b"time [s]\tvoltage [mV]\n0\t1000\n1\t2000\textra\n2\t3000\n"
    settings = {"event_id": "TSV-API", "_repairs": [
        {"operation": "drop_malformed_rows", "rows": [3]}]}
    kwargs = {"files": {"file": ("capture.TSV", contents, "text/tab-separated-values")},
              "data": {"options": json.dumps(settings), "validate": "true"}}
    preview = client.post("/ingestion/preview", **kwargs)
    assert preview.status_code == 200, preview.text
    assert preview.json()["validation"]["valid"] is True
    assert client.get("/events").json() == []
    imported = client.post("/ingestion/import", **kwargs)
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["event"]["signals"][0]["unit"] == "V"
    assert result["event"]["signals"][0]["values"] == pytest.approx([1, 3])
    assert result["original_file"]["filename"] == "capture.TSV"
    assert result["derived_file"]["filename"] == "reviewed_copy.tsv"
    original_id = result["original_file"]["file_id"]
    assert client.get(f"/events/TSV-API/files/{original_id}/download").content == contents
    from frib_ds.bootstrap import Services
    state["services"] = Services()
    assert len(client.get("/events/TSV-API/files").json()) == 2
    assert client.post("/ingestion/import", **kwargs).status_code == 409
