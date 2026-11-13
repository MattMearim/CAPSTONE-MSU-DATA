"""Reset controls exercise a fake API only; no project records are deleted."""
from __future__ import annotations

import copy
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import APP, Response, backend, open_page, st
from streamlit.testing.v1 import AppTest


@pytest.fixture
def reset_backend(backend, monkeypatch):
    counts = {"events": 2, "analyses": 1, "drafts": 1, "reviews": 1, "knowledge": 1,
        "documents": 2, "document_chunks": 4, "retrieval_vectors": 4, "event_files": 3,
        "audit_entries": 12, "stored_files": 9}
    state = {"counts": counts, "posts": [], "reset": False, "failure": None, "counts_failure": False}
    original_get, original_post = requests.get, requests.post

    def get(url, **kwargs):
        path = urlsplit(url).path
        if path == "/system/data":
            if state["counts_failure"]:
                return Response({"detail": "Storage is temporarily unavailable"}, 503)
            return Response({"counts": state["counts"]})
        if state["reset"] and path in {"/events", "/documents", "/knowledge"}:
            return Response([])
        return original_get(url, **kwargs)

    def post(url, **kwargs):
        if urlsplit(url).path != "/system/reset":
            return original_post(url, **kwargs)
        state["posts"].append(copy.deepcopy(kwargs))
        if state["failure"]:
            return Response({"detail": state["failure"]}, 503)
        removed = dict(state["counts"])
        state["counts"] = {key: 0 for key in removed}
        state["counts"]["audit_entries"] = 1
        state["reset"] = True
        return Response({"reset": True, "removed": removed, "remaining": state["counts"], "reset_id": "RESET-TEST"})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    return state


def confirm(app):
    app.checkbox(key="project_reset_acknowledged").check().run()
    app.text_input(key="project_reset_confirmation").set_value("RESET").run()
    return app


def test_reset_is_discoverable_and_requires_both_exact_confirmations(reset_backend):
    app = open_page("🏠 Home")
    assert any(item.label == "Reset project data" for item in app.sidebar.expander)
    assert app.button(key="project_reset_submit").disabled
    assert any("Stored files: 9" in item.value for item in app.markdown)
    assert any("original uploads and attachments" in item.value for item in app.warning)
    app.text_input(key="project_reset_confirmation").set_value("RESET").run()
    assert app.button(key="project_reset_submit").disabled
    app.checkbox(key="project_reset_acknowledged").check().run()
    assert not app.button(key="project_reset_submit").disabled
    app.text_input(key="project_reset_confirmation").set_value("reset").run()
    assert app.button(key="project_reset_submit").disabled
    assert reset_backend["posts"] == []


def test_success_clears_stale_data_and_returns_to_empty_home(reset_backend):
    app = open_page("🔎 Investigate Event")
    stale = {
        "analysis_RF-TEST": {"event_id": "RF-TEST"}, "draft_RF-TEST": {"summary": "old"},
        "rag_RF-TEST": {"answer": "old"}, "corpus_answer": {"answer": "old"},
        "document_download_DOC-1": b"old", "event_file_download_RF-TEST_FILE": b"old",
        "last_generated_event": {"event_id": "RF-TEST"}, "last_imported_event": {"event_id": "RF-TEST"},
        "csv_cached_preview": {"event": "old"}, "quality_saved_RF-TEST": {"status": "review"},
        "exports_investigate_RF-TEST": {"original": b"old"}, "selected_document": {"document_id": "DOC-1"},
    }
    for key, value in stale.items():
        app.session_state[key] = value
    confirm(app).button(key="project_reset_submit").click().run()
    assert not app.exception
    assert reset_backend["posts"][0]["json"] == {"confirmation": "RESET"}
    assert len(reset_backend["posts"]) == 1
    assert app.radio(key="main_nav").value == "🏠 Home"
    for key in stale:
        assert key not in app.session_state
    assert "investigate_event" not in app.session_state
    assert app.session_state["project_reset_generation"] == 1
    assert app.checkbox(key="project_reset_acknowledged").value is False
    assert app.text_input(key="project_reset_confirmation").value == ""
    assert any("Project data reset" in item.value for item in app.success)
    assert any(item.label == "Reset receipt" for item in app.expander)
    assert any(item.label == "Datasets" and item.value == "0" for item in app.metric)
    assert any("Project data is already empty" in item.value for item in app.info)
    app.run()
    assert not any("Project data reset" in item.value for item in app.success)
    assert len(reset_backend["posts"]) == 1


def test_reset_failure_preserves_inputs_and_cached_evidence_for_retry(reset_backend):
    app = open_page("🏠 Home")
    app.session_state["corpus_answer"] = {"answer": "preserved evidence"}
    reset_backend["failure"] = "Reset could not acquire the storage lock"
    confirm(app).button(key="project_reset_submit").click().run()
    assert not app.exception
    assert app.session_state["corpus_answer"] == {"answer": "preserved evidence"}
    assert app.checkbox(key="project_reset_acknowledged").value is True
    assert app.text_input(key="project_reset_confirmation").value == "RESET"
    assert not app.button(key="project_reset_submit").disabled
    assert any("storage lock" in item.value for item in app.error)
    assert not any("Project data reset" in item.value for item in app.success)
    reset_backend["failure"] = None
    app.button(key="project_reset_submit").click().run()
    assert not app.exception
    assert "corpus_answer" not in app.session_state
    assert len(reset_backend["posts"]) == 2


def test_unavailable_counts_prevent_reset_and_refresh_retries(reset_backend):
    reset_backend["counts_failure"] = True
    app = open_page("🏠 Home")
    confirm(app)
    assert app.button(key="project_reset_submit").disabled
    assert any("Storage is temporarily unavailable" in item.value for item in app.caption)
    assert reset_backend["posts"] == []
    reset_backend["counts_failure"] = False
    app.button(key="project_reset_refresh").click().run()
    assert not app.exception
    assert not app.button(key="project_reset_submit").disabled


@pytest.mark.parametrize("tab, key", [("Import data", "csv_import"), ("Text & PDF", "text_import"), ("Event JSON", "json_import")])
def test_uploaders_get_new_identities_after_reset(reset_backend, monkeypatch, tab, key):
    uploader_keys = []

    def upload(*args, **kwargs):
        uploader_keys.append(kwargs.get("key"))
        return None

    monkeypatch.setattr(st, "file_uploader", upload)
    app = open_page("🧪 Create Dataset", tab)
    assert key in uploader_keys
    confirm(app).button(key="project_reset_submit").click().run()
    uploader_keys.clear()
    app.session_state["workspace_tabs"] = tab
    app.radio(key="main_nav").set_value("🧪 Create Dataset").run()
    assert not app.exception
    assert f"{key}_reset_1" in uploader_keys
    assert not ({"csv_import", "text_import", "json_import"} & set(uploader_keys))
    app.radio(key="main_nav").set_value("📁 Files & Documents").run()
    assert "document_uploads_reset_1" in uploader_keys


def test_success_clears_streamlit_data_cache(reset_backend):
    calls = []

    @st.cache_data(show_spinner=False)
    def cached_evidence():
        calls.append(1)
        return "cached"

    cached_evidence.clear()
    cached_evidence()
    cached_evidence()
    assert len(calls) == 1
    app = open_page("🏠 Home")
    confirm(app).button(key="project_reset_submit").click().run()
    assert not app.exception
    cached_evidence()
    assert len(calls) == 2
    cached_evidence.clear()
