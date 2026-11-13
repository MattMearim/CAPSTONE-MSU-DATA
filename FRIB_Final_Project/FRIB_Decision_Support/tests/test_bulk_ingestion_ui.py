"""Bulk uploads require a deliberate start and expose each saved or failed file."""
from __future__ import annotations

import copy
from email import policy
from email.parser import BytesParser
import io
import json
import sys
import types

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


JOB_ID = "BULK-" + "a" * 32
LIMITS = {"max_files": 1000, "max_total_bytes": 1073741824, "max_file_bytes": 20971520,
          "supported_datasets": ["csv", "tsv", "json", "log"], "supported_documents": ["pdf", "txt", "md"],
          "archives": ["zip"], "documents_approved_by_default": False, "max_active_jobs": 2}


def report(status="queued"):
    return {"job_id": JOB_ID, "status": status, "total_files": 2, "processed_files": 0,
            "uploaded_bytes": 30, "expanded_bytes": 30, "counts": {"imported": 0, "failed": 0, "skipped": 0, "cancelled": 0},
            "files": [{"name": "capture.csv", "size_bytes": 20, "kind": "dataset", "status": "queued"},
                      {"name": "procedure.md", "size_bytes": 10, "kind": "document", "status": "queued"}],
            "limits": {key: LIMITS[key] for key in ("max_files", "max_total_bytes", "max_file_bytes")},
            "cancel_requested": False, "message": "Queued. Original files will be checked one at a time."}


class Upload(io.BytesIO):
    def __init__(self, name, contents=b"time_s,value\n0,1\n1,2\n"):
        super().__init__(contents)
        self.name, self.size, self.type = name, len(contents), "application/octet-stream"


@pytest.fixture
def bulk_ui(monkeypatch):
    state = {"files": [], "uploader_calls": [], "reads": [], "posts": [], "uploads": [], "navigations": [],
             "report": report(), "status_error": False, "upload_error": False}
    callbacks = types.ModuleType("frib_bulk_ui_test_backend")
    def api_get(path, *args, **kwargs):
        state["reads"].append(path)
        if path == "/ingestion/bulk/limits":
            return copy.deepcopy(LIMITS)
        assert path == f"/ingestion/bulk/{JOB_ID}", path
        if state["status_error"]:
            raise RuntimeError("Temporary status connection failure")
        return copy.deepcopy(state["report"])
    def api_post(path, payload=None, *args, **kwargs):
        state["posts"].append((path, payload))
        assert path == f"/ingestion/bulk/{JOB_ID}/cancel", path
        state["report"]["cancel_requested"] = True
        state["report"]["message"] = "The current file will finish safely; remaining files will be skipped."
        return copy.deepcopy(state["report"])
    def api_upload_batch(files, options, on_progress=None):
        state["uploads"].append(([item.name for item in files], copy.deepcopy(options)))
        if state["upload_error"]:
            raise RuntimeError("Upload was rejected: unsafe archive path")
        return copy.deepcopy(state["report"])
    callbacks.api_get, callbacks.api_post, callbacks.api_upload_batch = api_get, api_post, api_upload_batch
    callbacks.friendly_error = str
    callbacks.navigate_event = lambda event_id: state["navigations"].append(event_id)
    monkeypatch.setitem(sys.modules, callbacks.__name__, callbacks)
    def uploader(*args, **kwargs):
        state["uploader_calls"].append((args, kwargs))
        if kwargs.get("accept_multiple_files"):
            return state["files"]
        return state["files"][0] if state["files"] else None
    monkeypatch.setattr(st, "file_uploader", uploader)
    source = """
from frib_ds.dashboard.bulk_ui import render_bulk_importer
from frib_bulk_ui_test_backend import api_get, api_post, api_upload_batch, friendly_error, navigate_event
render_bulk_importer(api_get, api_post, api_upload_batch, friendly_error, navigate_event)
"""
    state["app"] = lambda: AppTest.from_string(source, default_timeout=15)
    return state


def page_text(app):
    return "\n".join(str(item.value) for item in [*app.markdown, *app.caption, *app.info, *app.warning, *app.error, *app.success])


def select_and_confirm(state, files=None):
    state["files"] = files or [Upload("collection.zip", b"ZIP contents are checked by the real API")]
    app = state["app"]().run()
    assert not app.exception
    app.checkbox(key="bulk_confirm").set_value(True).run()
    return app


def test_bulk_import_requires_files_and_confirmation_without_approving_documents(bulk_ui):
    app = bulk_ui["app"]().run()
    assert not app.exception
    assert app.button(key="bulk_submit").disabled
    assert app.checkbox(key="bulk_confirm").value is False
    assert not bulk_ui["uploads"] and not bulk_ui["posts"]
    bulk_ui["files"] = [Upload("collection.zip")]
    app.run()
    assert app.button(key="bulk_submit").disabled
    assert not any("approve" in item.label.lower() for item in app.checkbox)
    assert "/ingestion/bulk/limits" in bulk_ui["reads"]


def test_confirmed_batch_starts_once_and_polls_without_resubmitting(bulk_ui):
    app = select_and_confirm(bulk_ui)
    assert not app.button(key="bulk_submit").disabled
    app.button(key="bulk_submit").click().run()
    assert not app.exception
    assert bulk_ui["uploads"] == [(["collection.zip"], {})]
    assert app.session_state["bulk_job_id"] == JOB_ID
    assert app.button(key="bulk_submit").disabled
    app.run()
    assert len(bulk_ui["uploads"]) == 1
    assert f"/ingestion/bulk/{JOB_ID}" in bulk_ui["reads"]
    assert not bulk_ui["posts"]


def test_changing_selected_files_requires_a_fresh_confirmation(bulk_ui):
    app = select_and_confirm(bulk_ui, [Upload("first.zip")])
    assert not app.button(key="bulk_submit").disabled
    bulk_ui["files"] = [Upload("replacement.zip")]
    app.run()
    assert not app.exception
    assert app.checkbox(key="bulk_confirm").value is False
    assert app.button(key="bulk_submit").disabled
    assert not bulk_ui["uploads"]


def test_finished_job_stops_polling_and_retains_unapproved_document_result(bulk_ui):
    app = select_and_confirm(bulk_ui)
    app.button(key="bulk_submit").click().run()
    complete = report("completed")
    complete.update(processed_files=2, counts={"imported": 2, "failed": 0, "skipped": 0, "cancelled": 0})
    complete["files"][0].update(status="imported", event_id="EVENT-ONE")
    complete["files"][1].update(status="imported", document_id="DOC-ONE", approved=False)
    bulk_ui["report"] = complete
    app.run()
    assert not app.exception
    assert app.session_state["bulk_report"]["status"] == "completed"
    polls = bulk_ui["reads"].count(f"/ingestion/bulk/{JOB_ID}")
    app.run()
    assert bulk_ui["reads"].count(f"/ingestion/bulk/{JOB_ID}") == polls
    assert len(bulk_ui["uploads"]) == 1
    assert "without approval" in page_text(app)


def test_collection_picker_bounds_memory_before_receiving_a_folder(bulk_ui):
    app = bulk_ui["app"]().run()
    assert not app.exception
    options = bulk_ui["uploader_calls"][-1][1]
    assert options["accept_multiple_files"] is False
    assert options["type"] == ["zip"]
    assert options["max_upload_size"] == 1024
    assert "Finder" in page_text(app) and "Compress" in page_text(app)


def test_non_archive_or_multiple_selections_cannot_start_even_if_picker_is_bypassed():
    from frib_ds.dashboard.bulk_ui import validate_selection
    for uploads in ([Upload("capture.csv")], [Upload("one.zip"), Upload("two.zip")]):
        with pytest.raises(ValueError, match="one ZIP"):
            validate_selection(uploads, LIMITS)


def test_zip_picker_sends_one_archive_without_expanding_it_in_the_ui(bulk_ui):
    bulk_ui["files"] = [Upload("complete-run.zip", b"zip fixture is validated by the API")]
    app = bulk_ui["app"]().run()
    assert not app.exception
    options = bulk_ui["uploader_calls"][-1][1]
    assert not options.get("accept_multiple_files")
    assert "zip" in options["type"]
    app.checkbox(key="bulk_confirm").set_value(True).run()
    app.button(key="bulk_submit").click().run()
    assert bulk_ui["uploads"][0][0] == ["complete-run.zip"]


@pytest.mark.parametrize("options", ["{not JSON", "[]"])
def test_invalid_advanced_options_cannot_start_a_batch(bulk_ui, options):
    app = select_and_confirm(bulk_ui)
    app.text_area(key="bulk_options").set_value(options).run()
    if not app.button(key="bulk_submit").disabled:
        app.button(key="bulk_submit").click().run()
    assert not app.exception
    assert not bulk_ui["uploads"]
    assert "shared import settings" in page_text(app).lower()


def test_cancel_stops_after_current_file_without_reuploading(bulk_ui):
    app = select_and_confirm(bulk_ui)
    app.button(key="bulk_submit").click().run()
    app.button(key="bulk_cancel").click().run()
    assert not app.exception
    assert [path for path, _ in bulk_ui["posts"]] == [f"/ingestion/bulk/{JOB_ID}/cancel"]
    assert len(bulk_ui["uploads"]) == 1
    assert app.button(key="bulk_cancel").disabled
    assert app.session_state["bulk_report"]["cancel_requested"] is True


def test_mixed_completed_results_show_failures_and_open_only_an_explicit_event(bulk_ui):
    completed = report("completed")
    completed.update(total_files=3, processed_files=3,
                     counts={"imported": 1, "failed": 1, "skipped": 1, "cancelled": 0},
                     files=[{"name": "capture.csv", "size_bytes": 20, "kind": "dataset", "status": "imported", "event_id": "EVENT-BULK-ONE"},
                            {"name": "bad.csv", "size_bytes": 20, "kind": "dataset", "status": "failed", "error": "Time column requires review"},
                            {"name": "readme.exe", "size_bytes": 10, "kind": "unsupported", "status": "skipped", "message": "Unsupported file type"}])
    bulk_ui["report"] = completed
    app = bulk_ui["app"]()
    app.session_state["bulk_job_id"] = JOB_ID
    app.session_state["bulk_report"] = completed
    app.run()
    assert not app.exception
    assert not bulk_ui["navigations"]
    assert any("report" in item.label.lower() for item in app.get("download_button"))
    app.button(key="bulk_explore").click().run()
    assert bulk_ui["navigations"] == ["EVENT-BULK-ONE"]
    assert not bulk_ui["uploads"] and not bulk_ui["posts"]
    visible = page_text(app) + "\n".join(str(frame.value) for frame in app.dataframe)
    assert "bad.csv" in visible and "Time column requires review" in visible


def test_poll_failure_retains_job_identity_and_does_not_resubmit(bulk_ui):
    app = select_and_confirm(bulk_ui)
    app.button(key="bulk_submit").click().run()
    bulk_ui["status_error"] = True
    app.run()
    assert not app.exception
    assert "Temporary status connection failure" in page_text(app)
    assert app.session_state["bulk_job_id"] == JOB_ID
    assert app.button(key="bulk_submit").disabled
    assert len(bulk_ui["uploads"]) == 1


def test_upload_error_is_actionable_without_claiming_a_started_job(bulk_ui):
    bulk_ui["upload_error"] = True
    app = select_and_confirm(bulk_ui)
    app.button(key="bulk_submit").click().run()
    assert not app.exception
    assert "unsafe archive path" in page_text(app)
    with pytest.raises(KeyError):
        app.session_state["bulk_job_id"]
    assert not bulk_ui["posts"]


def test_streamed_multipart_uses_bounded_reads_and_retains_relative_filenames():
    from frib_ds.dashboard.bulk_client import MultipartBatch
    class BoundedUpload(Upload):
        def __init__(self, name, contents):
            super().__init__(name, contents)
            self.read_sizes = []
        def read(self, size=-1):
            assert 0 <= size <= MultipartBatch.chunk_size
            self.read_sizes.append(size)
            return super().read(size)
        def getvalue(self):
            pytest.fail("Multipart transfer must not duplicate entire selected files")
    contents = b"x" * (MultipartBatch.chunk_size * 2 + 17)
    upload = BoundedUpload('run-1/capture "checked".csv', contents)
    progress = []
    batch = MultipartBatch([upload], {"domain": "other"}, on_progress=lambda sent, total: progress.append((sent, total)))
    body = b"".join(batch)
    assert len(body) == len(batch)
    assert upload.read_sizes == [MultipartBatch.chunk_size, MultipartBatch.chunk_size, 17]
    assert progress[-1] == (len(batch), len(batch))
    assert all(left[0] <= right[0] for left, right in zip(progress, progress[1:]))
    envelope = f"Content-Type: {batch.content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    parts = list(BytesParser(policy=policy.default).parsebytes(envelope).iter_parts())
    assert parts[0].get_param("name", header="content-disposition") == "options"
    assert json.loads(parts[0].get_payload(decode=True)) == {"domain": "other"}
    assert parts[1].get_param("name", header="content-disposition") == "approved_documents"
    assert parts[1].get_payload(decode=True) == b"false"
    assert parts[2].get_filename() == 'run-1/capture "checked".csv'
    assert parts[2].get_payload(decode=True) == contents


@pytest.mark.parametrize("filename", ["capture\r\nInjected: header.csv", "bad\x00name.csv"])
def test_multipart_rejects_control_characters_in_filenames(filename):
    from frib_ds.dashboard.bulk_client import MultipartBatch
    with pytest.raises(ValueError, match="control characters"):
        MultipartBatch([Upload(filename)])


def test_changed_upload_fails_without_claiming_complete_transfer():
    from frib_ds.dashboard.bulk_client import MultipartBatch
    upload = Upload("capture.csv", b"complete contents")
    progress = []
    batch = MultipartBatch([upload], on_progress=lambda sent, total: progress.append((sent, total)))
    upload.truncate(3)
    with pytest.raises(ValueError, match="changed while uploading"):
        b"".join(batch)
    assert not progress or progress[-1][0] < len(batch)
