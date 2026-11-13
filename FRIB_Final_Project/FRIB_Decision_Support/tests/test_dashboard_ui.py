"""Exercise important UI actions without reaching a server or modifying project data."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

st = pytest.importorskip("streamlit", reason="Dashboard tests require the optional ui dependencies")
from streamlit.testing.v1 import AppTest
from frib_ds.dashboard.event_view import signal_figure
from frib_ds.dashboard.navigation import ADDITION_ITEMS, LEGACY_SECTIONS


APP = Path(__file__).resolve().parents[1] / "src" / "frib_ds" / "dashboard" / "app.py"


class Response:
    def __init__(self, payload=None, status=200, content=b"original evidence"):
        self.payload, self.status_code, self.content = payload, status, content
        self.ok = status < 400
        self.text = json.dumps(payload)

    def json(self):
        return copy.deepcopy(self.payload)


class Upload:
    def __init__(self, name, content, mime="application/json"):
        self.name, self.content, self.type = name, content, mime

    def getvalue(self):
        return self.content


@pytest.fixture
def backend(monkeypatch):
    event = {"event_id": "RF-TEST", "domain": "rf", "event_type": "cavity_trip", "timestamp": "2026-10-09T12:00:00Z", "metadata": {"dataset_name": "Test event"}, "signals": [{"name": "cavity_field", "unit": "MV/m", "sample_rate_hz": 10.0, "timestamps_s": [0.0, 0.1, 0.2], "values": [1.0, 0.8, 0.2]}], "states": [], "logs": [], "attachments": [], "provenance": {"source": "original test", "checksum": "original checksum"}}
    draft = {"draft_id": "DRAFT-TEST", "event_id": "RF-TEST", "summary": "Draft summary", "observations": ["Field decreased"], "hypotheses": [{"rank": 1, "description": "Possible trip", "support": "moderate", "supporting_evidence": ["Field trace"], "contradicting_evidence": []}], "recommended_actions": ["Check evidence"], "affected_hardware": ["Cavity 1"], "relevant_sources": ["DOC-1:CHUNK-1"], "tags": ["rf"], "status": "draft", "generated_by": "deterministic_fallback"}
    analysis = {"event_id": "RF-TEST", "processor": "test", "processor_version": "1.0", "features": {"peak": 1.0, "processing": {"alignment": "common grid"}, "warnings": ["Synthetic evidence"]}, "findings": ["Field decreased"], "timeline": [{"timestamp_s": 0.1, "event": "Trip", "evidence": "Field"}], "plot_specs": [{"kind": "timeseries", "timestamps_s": [0.0, 0.1, 0.2], "values": {"cavity_field": [1.0, 0.8, 0.2]}, "units": {"cavity_field": "MV/m"}}, {"kind": "fft", "frequencies_hz": [0.0, 5.0], "amplitudes": [0.0, 1.0], "amplitude_unit": "MV/m"}]}
    document = {"document_id": "DOC-1", "filename": "procedure.txt", "title": "Procedure", "version": "Rev 1", "approved": False, "uploaded_at": "2026-10-09T12:00:00Z", "checksum": "source checksum", "size_bytes": 12, "indexed_chunks": 0}
    preview = {"format": "csv", "filename": "data.csv", "row_count": 3, "columns": [{"name": "time_s", "suggested_role": "numeric", "suggested_unit": "s", "examples": ["0", "0.1", "0.2"]}, {"name": "cavity_field", "suggested_role": "numeric", "suggested_unit": "MV/m", "examples": ["1", "0.8", "0.2"]}], "sample_rows": [{"time_s": 0, "cavity_field": 1.0}], "suggested_time_column": "time_s", "suggested_time_unit": "s", "warnings": []}
    catalog = [{"symbol": symbol, "dimension": dimension, "canonical_unit": canonical, "aliases": [], "scale": scale, "offset": 0} for symbol, dimension, canonical, scale in [("s", "time", "s", 1), ("ms", "time", "s", 0.001), ("Pa", "pressure", "Pa", 1), ("kPa", "pressure", "Pa", 1000), ("W", "power", "W", 1), ("kW", "power", "W", 1000), ("V/m", "electric_field", "V/m", 1), ("MV/m", "electric_field", "V/m", 1000000)]]
    state = {"event": event, "draft": draft, "analysis": analysis, "documents": [document], "posts": [], "deletes": [], "gets": [], "event_files": [], "preview": preview, "preview_event": copy.deepcopy(event), "units": catalog, "validation_errors": []}

    def get(url, **kwargs):
        path = urlsplit(url).path
        state["gets"].append(path)
        if path == '/system/ai':
            return Response({'active': {'provider': 'ollama', 'model': 'qwen3:8b', 'base_url': 'http://127.0.0.1:11434',
                'temperature': 0.0, 'timeout_seconds': 300, 'context_length': 4096, 'max_output_tokens': 500},
                'profiles': [], 'active_profile': None, 'embeddings': {'model': 'all-MiniLM-L6-v2'}})
        if path == '/system/ai/models':
            return Response({'models': [{'id': 'qwen3:8b'}], 'download_available': False})
        if path == '/system/ai/setup':
            return Response({'status': 'idle'})
        if path == '/system/ai/recommendations':
            from frib_ds.ai_hardware import plan_models
            return Response(plan_models({'architecture': 'AMD64', 'cpu': {'model': 'Test', 'logical_cores': 8},
                'memory': {'total_gib': 16, 'available_gib': 8}, 'disk': {'free_gib': 100},
                'gpu': {'devices': [{'name': 'Test GPU', 'memory_gib': 4}]}}, []))
        payloads = {"/health": {"llm_provider": "mock", "embedding_provider": "hash", "domains": ["rf", "mechanical", "plc"]}, "/events": [{**{k: event[k] for k in ["event_id", "domain", "event_type", "timestamp"]}, "dataset_name": "Test event", "signal_count": 1}], "/events/RF-TEST": state["event"], "/events/RF-TEST/analysis": state["analysis"], "/events/RF-TEST/draft": state["draft"], "/events/RF-TEST/files": state["event_files"], "/documents": state["documents"], "/knowledge": [], "/generators": [{"domain": "rf", "generator": "rf_cavity_trip", "event_type": "cavity_trip", "defaults": {"duration_s": 2.0, "trip_time_s": 1.0, "noise_std": 0.01, "sample_rate_hz": 10}}], "/audit": [], "/units": state["units"]}
        if path.endswith("/download"):
            return Response()
        return Response(payloads[path]) if path in payloads else Response({"detail": "Not found"}, 404)

    def post(url, **kwargs):
        path = urlsplit(url).path
        state["posts"].append((path, copy.deepcopy(kwargs)))
        if path == "/drafts/DRAFT-TEST/review":
            payload = kwargs["json"]
            state["draft"] = copy.deepcopy(payload.get("corrected_draft") or state["draft"])
            state["draft"]["status"] = {"approve": "approved", "correct": "corrected", "escalate": "escalated"}[payload["decision"]]
            return Response({"saved": True})
        if path == "/documents/index":
            return Response({"document_id": "DOC-NEW", "indexed_chunks": 0})
        if path == "/events":
            state["event"] = copy.deepcopy(kwargs["json"])
            return Response({"event_id": state["event"]["event_id"]})
        if path == "/events/generate-custom":
            return Response(state["event"])
        if path == "/ingestion/preview":
            result = copy.deepcopy(state["preview"])
            if (kwargs.get("data") or {}).get("validate") == "true":
                result.update(event=copy.deepcopy(state["preview_event"]), summary={"input_rows": 3, "retained_rows": 3, "numeric_signals": len(state["preview_event"]["signals"]), "state_changes": len(state["preview_event"]["states"]), "log_entries": len(state["preview_event"]["logs"])}, validation={"valid": not state["validation_errors"], "errors": state["validation_errors"]})
            return Response(result)
        if path == "/ingestion/import":
            options = json.loads(kwargs["data"]["options"])
            imported = copy.deepcopy(state["preview_event"])
            imported["metadata"].update(options.get("metadata", {}))
            imported["provenance"]["imported_by"] = options.get("imported_by")
            state["event"] = imported
            return Response({"event": imported, "summary": {}, "original_file": {"file_id": "ORIGINAL-1"}})
        if path == "/units/convert":
            value = kwargs["json"]
            source = next(unit for unit in catalog if unit["symbol"] == value["from_unit"])
            target = next(unit for unit in catalog if unit["symbol"] == value["to_unit"])
            return Response({**value, "converted_value": value["value"] * source["scale"] / target["scale"], "dimension": source["dimension"]})
        if path.endswith("/files"):
            return Response({"file_id": "FILE-NEW"})
        if path == "/rag/query":
            return Response({"mode": "extractive", "answer": "Retrieved guidance", "sources": [{"label": "S1", "title": "Procedure", "document_id": "DOC-1", "chunk_id": "CHUNK-1", "version": "Rev 1", "page": 2, "excerpt": "Approved excerpt"}], "grounded": True})
        raise AssertionError(f"Unexpected UI post: {path}")

    def delete(url, **kwargs):
        path = urlsplit(url).path
        state["deletes"].append(path)
        if path == "/documents/DOC-1":
            state["documents"] = []
        return Response({"deleted": True})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "delete", delete)
    return state


def select_page(app, page):
    """Select a main destination or one utility section in the compact overview."""
    if page in LEGACY_SECTIONS:
        app.session_state["addition_section"] = LEGACY_SECTIONS[page]
        page = ADDITION_ITEMS
    app.radio(key="main_nav").set_value(page).run()
    assert not app.exception
    return app


def open_page(page, workspace_tab=None):
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    if workspace_tab is not None:
        app.session_state["workspace_tabs"] = workspace_tab
    return select_page(app, page)


def test_inactive_dataset_tabs_do_not_load_their_catalogs_or_controls(backend):
    app = open_page("🏠 Home")
    backend["gets"].clear()
    app.radio(key="main_nav").set_value("🧪 Create Dataset").run()
    assert not app.exception
    assert "/generators" not in backend["gets"]
    assert "/events" not in backend["gets"]
    assert not any(button.label == "✨ Generate dataset" for button in app.button)
    assert not any(item.key == "library_search" for item in app.text_input)
    assert not backend["posts"]


@pytest.mark.parametrize("page", ["🏠 Home", "🧪 Create Dataset", "🔎 Investigate Event", "📁 Files & Documents", "💬 Ask Assistant", "✅ Review Results", "🧠 Engineering Wiki", "⚙️ Settings", "❓ Help"])
def test_pages_render_with_connected_demo_backend(backend, page):
    app = open_page(page)
    assert any("Demo mode" in item.value and "demonstration model" in item.value for item in app.markdown)


def test_named_review_acknowledgement_and_corrections_are_persisted(backend):
    app = open_page("✅ Review Results")
    submit_key = "review_DRAFT-TEST_submit"
    assert app.button(key=submit_key).disabled
    app.button(key="review_DRAFT-TEST_select_correct").click().run()
    app.text_area(key="review_DRAFT-TEST_summary").set_value("Corrected engineering summary")
    app.text_area(key="review_DRAFT-TEST_observations").set_value("Reviewed field trace")
    app.text_input(key="review_DRAFT-TEST_reviewer").set_value("Jane Smith, RF engineer").run()
    assert app.button(key=submit_key).disabled
    app.checkbox(key="review_DRAFT-TEST_acknowledged").check().run()
    assert not app.button(key=submit_key).disabled
    app.button(key=submit_key).click().run()
    assert not app.exception
    review = next(kwargs["json"] for path, kwargs in backend["posts"] if path.endswith("/review"))
    assert review["reviewer"] == "Jane Smith, RF engineer"
    assert review["corrected_draft"]["summary"] == "Corrected engineering summary"
    assert review["corrected_draft"]["observations"] == ["Reviewed field trace"]
    assert review["corrected_draft"]["relevant_sources"] == ["DOC-1:CHUNK-1"]
    assert backend["draft"]["status"] == "corrected"
    assert not any(button.key == submit_key for button in app.button)
    assert any("cannot be reviewed again" in item.value for item in app.success)


def test_document_delete_requires_confirmation_and_clears_answers(backend):
    app = open_page("📁 Files & Documents")
    assert app.button(key="delete_document_DOC-1").disabled
    app.session_state["corpus_answer"] = {"answer": "stale answer"}
    app.checkbox(key="confirm_document_DOC-1").check().run()
    app.button(key="delete_document_DOC-1").click().run()
    assert not app.exception
    assert backend["deletes"] == ["/documents/DOC-1"]
    assert "corpus_answer" not in app.session_state
    assert any("Document and its searchable excerpts deleted" in item.value for item in app.success)


def test_multiple_document_uploads_default_to_unapproved(backend, monkeypatch):
    uploads = [Upload("first.txt", b"first", "text/plain"), Upload("second.md", b"second", "text/markdown")]
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: uploads if kw.get("key") == "document_uploads" else None)
    app = open_page("📁 Files & Documents")
    next(button for button in app.button if button.label == "Add files").click().run()
    assert not app.exception
    posts = [kwargs for path, kwargs in backend["posts"] if path == "/documents/index"]
    assert len(posts) == 2
    assert [post["data"]["approved"] for post in posts] == ["false", "false"]
    assert [post["files"]["file"][0] for post in posts] == ["first.txt", "second.md"]


def test_json_import_preserves_supplied_id_provenance_and_original_bytes(backend, monkeypatch):
    original = copy.deepcopy(backend["event"])
    original["event_id"] = "EXTERNAL-EVENT-123"
    raw = json.dumps(original).encode()
    upload = Upload("event.json", raw)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "json_import" else None)
    app = open_page("🧪 Create Dataset", "Event JSON")
    next(button for button in app.button if button.label == "Import event JSON").click().run()
    assert not app.exception
    event_post = next(kwargs["json"] for path, kwargs in backend["posts"] if path == "/events")
    assert event_post == original
    attachment = next(kwargs for path, kwargs in backend["posts"] if path == "/events/EXTERNAL-EVENT-123/files")
    assert attachment["files"]["file"][1] == raw


def test_backend_validation_detail_is_visible(backend, monkeypatch):
    def bad_post(*args, **kwargs):
        return Response({"detail": [{"loc": ["body", "signals", 0, "values"], "msg": "values must be finite"}]}, 422)

    monkeypatch.setattr(requests, "post", bad_post)
    app = open_page("💬 Ask Assistant")
    next(area for area in app.text_area if area.label == "Question").set_value("How should evidence be reviewed?").run()
    next(button for button in app.button if button.label == "Search approved documents").click().run()
    assert any("signals.0.values: values must be finite" in item.value for item in app.error)


def test_generator_preserves_simple_controls(backend):
    app = open_page("🧪 Create Dataset", "Generate demo")
    app.text_input(key="gen_context_rf_cavity").set_value("Cavity 1")
    app.number_input(key="gen_rf_trip_time_s").set_value(0.5).run()
    next(button for button in app.button if button.label == "✨ Generate dataset").click().run()
    assert not app.exception
    generated = next(kwargs["json"] for path, kwargs in backend["posts"] if path == "/events/generate-custom")
    assert generated["generator"] == "rf_cavity_trip"
    assert generated["overrides"]["trip_time_s"] == 0.5
    assert generated["overrides"]["sample_rate_hz"] == 10.0
    assert generated["metadata"] == {"cavity": "Cavity 1"}


def test_csv_import_preserves_original_and_does_not_interpolate(backend, monkeypatch):
    raw = b"time_s,cavity_field\n0.0,1.0\n0.1,0.8\n0.2,0.2\n"
    upload = Upload("data.csv", raw, "text/csv")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    app = open_page("🧪 Create Dataset")
    app.text_input(key="csv_context_captured_by").set_value("Jane Smith")
    app.text_input(key="csv_context_beam_state").set_value("No beam")
    next(box for box in app.selectbox if box.label == "Time column").set_value("time_s").run()
    next(button for button in app.button if button.label == "📥 Import dataset").click().run()
    assert not app.exception
    event = backend["event"]
    assert event["signals"][0]["values"] == [1.0, 0.8, 0.2]
    assert event["signals"][0]["timestamps_s"] == [0.0, 0.1, 0.2]
    assert event["provenance"]["checksum"]
    assert event["provenance"]["imported_by"] == "Jane Smith"
    assert event["metadata"]["beam_state"] == "No beam"
    request = next(kwargs for path, kwargs in backend["posts"] if path == "/ingestion/import")
    assert request["files"]["file"][1] == raw
    mapping = json.loads(request["data"]["options"])
    assert mapping["column_roles"] == {"cavity_field": "numeric"}
    assert mapping["time_column"] == "time_s"


def test_analysis_renders_field_emission_and_state_timeline(backend):
    backend["analysis"]["plot_specs"].extend([
        {"kind": "scatter", "x": [1.0, 2.0], "y": [3.0, 4.0], "x_label": "Gradient", "y_label": "X-ray", "x_unit": "MV/m", "y_unit": "mSv/h"},
        {"kind": "state_timeline", "timestamps_s": [0.0, 1.0], "states": ["RUNNING", "INTERLOCKED"], "state_name": "PLC_STATE"},
    ])
    app = open_page("🔎 Investigate Event")
    assert not app.exception
    # Evidence and analysis are rendered only in their selected panels.
    assert len(app.get("plotly_chart")) == 1
    app.button(key="workflow_next").click().run()
    assert not app.exception
    # Aligned signals, spectrum, field-emission scatter, and PLC steps.
    assert len(app.get("plotly_chart")) == 4


def test_event_deletion_clears_event_and_file_cache(backend):
    app = open_page("🧪 Create Dataset", "Dataset library")
    app.session_state["last_generated_event"] = backend["event"]
    app.session_state["draft_RF-TEST"] = backend["draft"]
    app.session_state["analysis_RF-TEST"] = backend["analysis"]
    app.session_state["event_file_download_RF-TEST_FILE-1"] = b"old file"
    app.session_state["corpus_answer"] = {"answer": "stale answer"}
    app.checkbox(key="confirm_RF-TEST").check().run()
    next(button for button in app.button if button.label == "🗑 Delete dataset").click().run()
    assert not app.exception
    assert backend["deletes"] == ["/events/RF-TEST"]
    for key in ["last_generated_event", "draft_RF-TEST", "analysis_RF-TEST", "event_file_download_RF-TEST_FILE-1", "corpus_answer"]:
        assert key not in app.session_state


def test_mixed_csv_mapping_keeps_categories_logs_and_per_row_units(backend, monkeypatch):
    raw = b"time_ms,pressure,pressure_unit,mode,note\n0,1,kPa,ON,Ready\n100,2,kPa,OFF,WARNING stop\n"
    upload = Upload("mixed.csv", raw, "text/csv")
    backend["preview"].update(columns=[{"name": "time_ms", "suggested_role": "numeric", "suggested_unit": "ms"}, {"name": "pressure", "suggested_role": "numeric", "suggested_unit": "kPa", "suggested_unit_column": "pressure_unit"}, {"name": "pressure_unit", "suggested_role": "ignore"}, {"name": "mode", "suggested_role": "category"}, {"name": "note", "suggested_role": "log"}], suggested_time_column="time_ms", suggested_time_unit="ms")
    backend["preview_event"]["signals"] = [{"name": "pressure", "unit": "Pa", "timestamps_s": [0.0, 0.1], "values": [1000.0, 2000.0]}]
    backend["preview_event"]["states"] = [{"name": "mode", "timestamp_s": 0.0, "value": "ON"}, {"name": "mode", "timestamp_s": 0.1, "value": "OFF"}]
    backend["preview_event"]["logs"] = [{"timestamp_s": 0.1, "level": "WARNING", "message": "Stop reported", "source": "mixed.csv"}]
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    prefix = "csv_" + hashlib.sha256(raw).hexdigest()[:12]
    assert app.selectbox(key=f"{prefix}_pressure_unit_column").value == "pressure_unit"
    app.text_input(key=f"{prefix}_pressure_source_unit").set_value("kPa").run()
    next(button for button in app.button if button.label == "📥 Import dataset").click().run()
    request = next(kwargs for path, kwargs in backend["posts"] if path == "/ingestion/import")
    options = json.loads(request["data"]["options"])
    assert options["column_roles"] == {"pressure": "numeric", "pressure_unit": "ignore", "mode": "category", "note": "log"}
    assert options["unit_columns"] == {"pressure": "pressure_unit"}
    assert options["source_units"]["pressure"] == "kPa"
    assert options["time_unit"] == "ms"
    assert options["target_units"] == {}
    assert request["files"]["file"][1] == raw


def test_invalid_mapping_blocks_commit_and_shows_issue(backend, monkeypatch):
    backend["validation_errors"] = ["Column pressure mixes pressure and temperature units; correct row 2."]
    upload = Upload("data.csv", b"time_s,cavity_field\n0,1\n1,2\n", "text/csv")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    app = open_page("🧪 Create Dataset")
    assert next(button for button in app.button if button.label == "📥 Import dataset").disabled
    assert any("correct row 2" in item.value for item in app.error)
    assert not any(path == "/ingestion/import" for path, _ in backend["posts"])


def test_text_only_import_and_record_order_plot(backend, monkeypatch):
    raw = b"WARNING tuner unavailable\nOperator checked status\n"
    upload = Upload("shift.log", raw, "text/plain")
    backend["preview"] = {"format": "text", "filename": upload.name, "row_count": 2, "columns": [], "sample_rows": [{"line": 1, "message": "WARNING tuner unavailable"}], "text_preview": raw.decode(), "warnings": ["No measured timestamps were found."]}
    backend["preview_event"].update(signals=[], states=[], logs=[{"timestamp_s": 0.0, "level": "WARNING", "message": "tuner unavailable", "source": upload.name}, {"timestamp_s": 1.0, "level": "INFO", "message": "Operator checked status", "source": upload.name}], metadata={"import_summary": {"time_basis": "row_index"}})
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "text_import" else None)
    app = open_page("🧪 Create Dataset", "Text & PDF")
    assert not app.exception
    assert any("No numeric channels" in item.value for item in app.caption)
    assert any("No measured timestamps" in item.value for item in app.warning)
    next(button for button in app.button if button.label == "Save text evidence event").click().run()
    request = next(kwargs for path, kwargs in backend["posts"] if path == "/ingestion/import")
    assert request["files"]["file"][1] == raw
    assert any(button.label == "Open imported event in Investigate" for button in app.button)


def test_unit_converter_uses_dimension_compatible_units(backend):
    app = open_page("🧪 Create Dataset")
    app.selectbox(key="create_units_dimension").set_value("pressure").run()
    app.number_input(key="create_units_value").set_value(2.0)
    app.selectbox(key="create_units_from_pressure").set_value("kPa")
    app.selectbox(key="create_units_to_pressure").set_value("Pa").run()
    app.button(key="create_units_convert").click().run()
    assert not app.exception
    assert any("2 kPa = 2000 Pa" in item.value for item in app.success)
    request = next(kwargs["json"] for path, kwargs in backend["posts"] if path == "/units/convert")
    assert request == {"value": 2.0, "from_unit": "kPa", "to_unit": "Pa"}


def test_signal_plot_labels_units_and_independent_axes():
    signals = [{"name": "pressure", "unit": "Pa", "timestamps_s": [0, 1, 2], "values": [1, 2, 3]}, {"name": "temperature", "unit": "K", "timestamps_s": [0, 0.5, 1], "values": [290, 291, 292]}]
    figure = signal_figure(signals, {"pressure": "Tuner pressure", "temperature": "Bearing temperature"}, (0, 1), title="Measured operating data")
    assert figure.layout.title.text == "Measured operating data"
    assert "Pa" in figure.layout.yaxis.title.text
    assert "K" in figure.layout.yaxis2.title.text
    assert figure.layout.xaxis2.title.text == "Elapsed time (s)"
    assert figure.data[0].yaxis != figure.data[1].yaxis
    assert list(figure.data[0].x) == [0, 1]
    assert list(figure.data[1].x) == [0, 0.5, 1]


def test_explorer_filters_and_editable_display_labels(backend):
    app = open_page("🔎 Investigate Event")
    app.text_input(key="view_investigate_RF-TEST_label_cavity_field").set_value("Cavity A accelerating field").run()
    assert not app.exception
    app.multiselect(key="view_investigate_RF-TEST_signals").set_value([]).run()
    assert any("Select a numeric channel" in item.value for item in app.info)


def test_actual_mixed_parser_reaches_valid_preview_and_preserves_plc_name(backend, monkeypatch):
    from frib_ds.ingestion import inspect_upload, build_event
    from frib_ds.units import normalize_event_units

    raw = (APP.parents[3] / "sample_data" / "mixed_units_and_states.csv").read_bytes()
    upload = Upload("mixed_units_and_states.csv", raw, "text/csv")
    original_post = requests.post

    def parser_post(url, **kwargs):
        if urlsplit(url).path == "/ingestion/preview":
            name, content, _ = kwargs["files"]["file"]
            preview = inspect_upload(name, content)
            if (kwargs.get("data") or {}).get("validate") == "true":
                try:
                    event = normalize_event_units(build_event(name, content, json.loads(kwargs["data"]["options"])))
                    backend["preview_event"] = event.model_dump(mode="json")
                    preview.update(event=backend["preview_event"], summary=event.metadata["import_summary"], validation={"valid": True, "errors": []})
                except ValueError as exc:
                    preview["validation"] = {"valid": False, "errors": [str(exc)]}
            return Response(preview)
        return original_post(url, **kwargs)

    monkeypatch.setattr(requests, "post", parser_post)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    prefix = "csv_" + hashlib.sha256(raw).hexdigest()[:12]
    assert app.text_input(key=f"{prefix}_PLC_STATE_name").value == "PLC_STATE"
    assert not next(button for button in app.button if button.label == "📥 Import dataset").disabled
    event = backend["preview_event"]
    assert [signal["unit"] for signal in event["signals"]] == ["Pa", "K"]
    assert {state["name"] for state in event["states"]} == {"PLC_STATE", "enabled"}
    assert len(event["logs"]) == 5
    next(button for button in app.button if button.label == "📥 Import dataset").click().run()
    assert not app.exception
    assert next(button for button in app.button if button.label == "📥 Import dataset").disabled
    assert len([path for path, _ in backend["posts"] if path == "/ingestion/import"]) == 1


def test_event_exports_use_original_and_standardized_backend_routes(backend):
    app = open_page("🔎 Investigate Event")
    app.button(key="exports_investigate_RF-TEST_prepare").click().run()
    assert not app.exception
    assert backend["gets"].count("/events/RF-TEST/download") == 3
    downloads = app.get("download_button")
    assert {item.label for item in downloads} >= {"Original event JSON", "Standardized JSON", "Standardized CSV"}
