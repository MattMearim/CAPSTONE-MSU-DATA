"""Quality choices are explicit, cached and separate from preserved evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import APP, Response, Upload, backend, open_page, st
from frib_ds.dashboard.event_view import signal_figure


def issue(code="DUPLICATE_ROWS", severity="warning", repair=None):
    return {"code": code, "severity": severity, "title": "Repeated source row", "message": "The file repeats an exact row.", "column": "cavity_field", "rows": [3], "timestamps_s": [0.2], "count": 1, "suggestion": "Check whether the repeated record is intentional.", "repair": repair}


def report(stage="L1", issues=None):
    issues = issues or []
    summary = {severity: sum(entry["severity"] == severity for entry in issues) for severity in ["error", "warning", "info"]}
    return {"stage": stage, "status": "blocked" if summary["error"] else "review" if summary["warning"] else "ok", "summary": summary, "issues": issues, "unit_suggestions": []}


@pytest.fixture
def quality_backend(backend, monkeypatch):
    state = {"raw": report(issues=[issue(repair={"operation": "drop_exact_duplicate_rows"})]), "malformed": False, "quality_calls": [], "preview_options": [], "saved_checks": []}
    original_post = requests.post

    def post(url, **kwargs):
        path = urlsplit(url).path
        if path == "/ingestion/quality":
            state["quality_calls"].append(copy.deepcopy(kwargs))
            return Response(state["raw"])
        if path == "/events/RF-TEST/quality":
            state["saved_checks"].append(copy.deepcopy(kwargs["json"]))
            return Response(report("L2", [issue("MISSING_INTERVAL")]))
        response = original_post(url, **kwargs)
        if path == "/ingestion/preview":
            options = json.loads((kwargs.get("data") or {}).get("options", "{}"))
            state["preview_options"].append(options)
            repaired = bool(options.get("_repairs"))
            result = response.json()
            result["quality"] = {"original_l1": state["raw"], "l1": report() if repaired else state["raw"], "l2": report("L2", [issue("MISSING_INTERVAL")]) if result.get("event") else None}
            if state["malformed"] and not repaired:
                result.update(columns=[], validation={"valid": False, "errors": ["Malformed source row 3 needs review."]})
                result.pop("event", None)
            if repaired:
                result["repair_receipt"] = {"operations": options["_repairs"], "original_preserved": True}
            return Response(result)
        return response

    monkeypatch.setattr(requests, "post", post)
    return state


def upload_csv(monkeypatch):
    upload = Upload("quality.csv", b"time_s,cavity_field\n0,1\n0.1,0.8\n0.1,0.8\n", "text/csv")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    return upload, "csv_" + hashlib.sha256(upload.content).hexdigest()[:12]


def test_source_quality_visible_and_repair_never_selected_automatically(quality_backend, monkeypatch):
    _, key = upload_csv(monkeypatch)
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    assert any("Repeated source row" in warning.value for warning in app.warning)
    assert app.checkbox(key=f"{key}_repair_0").value is False
    assert all(not options.get("_repairs") for options in quality_backend["preview_options"])
    assert len(quality_backend["quality_calls"]) == 1
    app.text_input(key=f"{key}_name").set_value("Reviewed capture").run()
    assert len(quality_backend["quality_calls"]) == 1
    assert not app.exception


def test_explicit_repair_repreviews_and_imports_identical_selection(quality_backend, backend, monkeypatch):
    _, key = upload_csv(monkeypatch)
    app = open_page("🧪 Create Dataset")
    app.checkbox(key=f"{key}_repair_0").check().run()
    assert not app.exception
    assert quality_backend["preview_options"][-1]["_repairs"] == [{"operation": "drop_exact_duplicate_rows"}]
    assert any(item.label == "Selected repair receipt" for item in app.expander)
    next(button for button in app.button if button.label == "📥 Import dataset").click().run()
    options = json.loads(next(kwargs["data"]["options"] for path, kwargs in backend["posts"] if path == "/ingestion/import"))
    assert options["_repairs"] == [{"operation": "drop_exact_duplicate_rows"}]
    assert "quality_expectations" in options and "settings" not in options


def test_malformed_file_quality_and_selected_physical_rows_remain_accessible(quality_backend, monkeypatch):
    _, key = upload_csv(monkeypatch)
    quality_backend.update(malformed=True, raw=report(issues=[issue("MALFORMED_ROWS", "error", {"operation": "drop_malformed_rows", "rows": [3]})]))
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    assert any("Malformed source row 3" in item.value for item in app.error)
    assert not any(button.label == "📥 Import dataset" for button in app.button)
    app.checkbox(key=f"{key}_repair_0").check().run()
    assert not app.exception
    assert quality_backend["preview_options"][-1]["_repairs"] == [{"operation": "drop_malformed_rows", "rows": [3]}]
    assert not next(button for button in app.button if button.label == "📥 Import dataset").disabled


def test_unit_hints_require_manual_source_assignment(quality_backend, monkeypatch):
    _, key = upload_csv(monkeypatch)
    quality_backend["raw"]["unit_suggestions"] = [{"column": "cavity_field", "candidates": [{"unit": "V/m", "confidence": "low", "evidence": ["Name may denote an electric field."]}], "requires_confirmation": True, "assigned": False}]
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    assert any("not assigned physical units" in item.value for item in app.caption)
    assert app.text_input(key=f"{key}_cavity_field_source_unit").value == "MV/m"


def test_invalid_explicit_repair_rows_cannot_be_saved(quality_backend, monkeypatch):
    _, key = upload_csv(monkeypatch)
    quality_backend["raw"] = report(issues=[issue("INVALID_NUMERIC", repair={"operation": "drop_invalid_numeric_cells", "columns": ["cavity_field"], "rows": [3]})])
    app = open_page("🧪 Create Dataset")
    app.checkbox(key=f"{key}_repair_0").check().run()
    app.text_input(key=f"{key}_repair_rows_0").set_value("all").run()
    assert not app.exception
    assert any("explicit positive source row" in item.value for item in app.error)
    assert next(button for button in app.button if button.label == "📥 Import dataset").disabled


def test_saved_quality_controls_submit_si_expectations_once_and_download(quality_backend):
    app = open_page("🔎 Investigate Event")
    key = "quality_saved_RF-TEST"
    app.checkbox(key=f"{key}_cadence_enabled").check().run()
    app.number_input(key=f"{key}_cadence").set_value(0.1)
    app.text_input(key=f"{key}_required").set_value("cavity_field, pressure")
    app.multiselect(key=f"{key}_channels").set_value(["cavity_field"]).run()
    app.checkbox(key=f"{key}_cavity_field_stable").check().run()
    app.number_input(key=f"{key}_cavity_field_tolerance").set_value(0.02)
    app.checkbox(key=f"{key}_cavity_field_max_enabled").check().run()
    app.number_input(key=f"{key}_cavity_field_max").set_value(1.0)
    app.button(key=f"{key}_check").click().run()
    assert not app.exception
    assert quality_backend["saved_checks"] == [{"expectations": {"expected_interval_s": 0.1, "gap_factor": 1.8, "required_channels": ["cavity_field", "pressure"], "channels": {"cavity_field": {"max": 1.0, "expected_stable": True, "stability_tolerance": 0.02}}}}]
    assert any(item.label == "Download quality report (JSON)" for item in app.get("download_button"))
    app.text_input(key=f"{key}_search").set_value("nonexistent").run()
    assert any("No issues match" in item.value for item in app.info)
    assert len(quality_backend["saved_checks"]) == 1


def test_quality_plot_breaks_missing_interval_without_changing_samples():
    source = {"name": "pressure", "unit": "Pa", "timestamps_s": [0, 1, 2, 8, 9], "values": [1, 1, 2, 2, 2]}
    original = copy.deepcopy(source)
    quality = report("L2", [{**issue("MISSING_INTERVAL"), "column": "pressure", "timestamps_s": [8]}])
    quality["expectations"] = {"expected_interval_s": 1.0, "gap_factor": 3.0}
    figure = signal_figure([source], {"pressure": "Tuner pressure"}, (0, 9), quality_report=quality)
    assert source == original
    assert list(figure.data[0].x) == [0, 1, 2, None, 8, 9]
    assert figure.data[0].connectgaps is False
    assert len(figure.layout.shapes) == 1
    assert list(figure.data[1].x) == [8]


def test_downsampled_preview_uses_full_report_intervals_not_display_spacing():
    signal = {"name": "pressure", "unit": "Pa", "timestamps_s": [0, 10, 20], "values": [1, 2, 3], "metadata": {"preview_total_samples": 201}}
    quality = {**report("L2"), "expectations": {"expected_interval_s": 0.1}}
    figure = signal_figure([signal], {"pressure": "Pressure"}, (0, 20), quality_report=quality)
    assert None not in figure.data[0].x
    assert not figure.layout.shapes
    assert figure.data[0].mode == "markers"
    quality["issues"] = [{**issue("RECORDING_GAP"), "column": "pressure", "intervals": [{"start_s": 4.0, "end_s": 8.0}]}]
    figure = signal_figure([signal], {"pressure": "Pressure"}, (0, 20), quality_report=quality)
    assert list(figure.data[0].x) == [0, None, 10, 20]
    assert figure.layout.shapes[0].x0 == 4.0 and figure.layout.shapes[0].x1 == 8.0
    assert figure.data[0].mode == "markers"


@pytest.mark.parametrize("declared", [False, True])
def test_full_capture_breaks_all_gaps_beyond_bounded_report_examples(declared):
    times = [0.0]
    for _ in range(30):
        times.extend([times[-1] + 1.0, times[-1] + 2.0, times[-1] + 7.0])
    source = {"name": "pressure", "unit": "Pa", "timestamps_s": times, "values": [1.0] * len(times)}
    intervals = [{"start_s": times[index - 1], "end_s": times[index]} for index in range(3, len(times), 3)]
    quality = {**report("L2", [{**issue("RECORDING_GAP"), "column": "pressure", "count": 30, "intervals": intervals[:25]}]), "location_basis": "accepted_sample_index", "expectations": {"gap_factor": 1.8}}
    if declared:
        quality["expectations"]["channels"] = {"pressure": {"expected_interval_s": 1.0}}
    figure = signal_figure([source], {"pressure": "Pressure"}, (times[0], times[-1]), quality_report=quality)
    assert list(figure.data[0].x).count(None) == 30
    assert len(figure.layout.shapes) == 25
    assert figure.data[0].mode == "lines"
    # A narrow display must use the full capture's cadence rather than recomputing it from the window.
    figure = signal_figure([source], {"pressure": "Pressure"}, (times[-4], times[-1]), quality_report=quality)
    assert list(figure.data[0].x).count(None) == 1


@pytest.mark.parametrize("inferred_metadata,time_label", [(True, "Elapsed time (s)"), (False, "Record order"), (False, "Row order (timing not measured)")])
def test_ordinal_coordinates_do_not_infer_timing_gaps(inferred_metadata, time_label):
    signal = {"name": "pressure", "unit": "Pa", "timestamps_s": [0, 1, 2, 20], "values": [1, 2, 3, 4], "metadata": {"inferred_time": inferred_metadata}}
    quality = {**report("L2"), "location_basis": "accepted_sample_index", "expectations": {"expected_interval_s": 1.0}}
    figure = signal_figure([signal], {"pressure": "Pressure"}, (0, 20), time_label=time_label, quality_report=quality)
    assert None not in figure.data[0].x
    assert not figure.layout.shapes


def test_actual_quality_api_repair_reaches_reviewed_si_preview(backend, monkeypatch):
    from fastapi.testclient import TestClient
    from frib_ds.api.main import app as api_app

    raw = b"time [s],pressure [kPa]\n0,1\n1,2,unexpected\n2,2\n8,2\n"
    upload = Upload("malformed_capture.csv", raw, "text/csv")
    key = "csv_" + hashlib.sha256(raw).hexdigest()[:12]
    client = TestClient(api_app)
    original_post = requests.post
    previews = []

    def api_post(url, **kwargs):
        path = urlsplit(url).path
        if path in {"/ingestion/quality", "/ingestion/preview"}:
            response = client.post(path, files=kwargs["files"], data=kwargs.get("data"))
            payload = response.json()
            if path == "/ingestion/preview":
                previews.append(payload)
            return Response(payload, response.status_code)
        return original_post(url, **kwargs)

    monkeypatch.setattr(requests, "post", api_post)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: upload if kw.get("key") == "csv_import" else None)
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    repair = next(widget for widget in app.checkbox if "malformed rows" in widget.label)
    assert repair.value is False
    repair.check().run()
    assert not app.exception
    assert all("CSV row has the wrong field count" in entry.value for entry in app.error)
    final = next(preview for preview in reversed(previews) if preview.get("event"))
    assert final["validation"]["valid"] is True
    assert final["event"]["signals"][0]["unit"] == "Pa"
    assert final["event"]["provenance"]["checksum"] == hashlib.sha256(raw).hexdigest()
    assert final["repair_receipt"]
    assert final["quality"]["original_l1"]["status"] == "blocked"
    assert final["quality"]["l1"]["status"] != "blocked"
    assert app.text_input(key=f"{key}_repair_rows_0").value == "3"
    assert not next(button for button in app.button if button.label == "📥 Import dataset").disabled


def test_saved_original_and_repaired_quality_are_distinguished(quality_backend, backend):
    backend["event"]["metadata"].update(upload_quality=report(issues=[issue("MALFORMED_ROWS", "error")]), effective_upload_quality=report(), repair_receipt={"operations": [{"operation": "drop_malformed_rows", "rows": [3]}]})
    app = open_page("🔎 Investigate Event")
    assert not app.exception
    assert any("original-file report is historical" in item.value for item in app.caption)
    assert any("Event JSON contains the reviewed derived view" in item.value for item in app.info)
    assert {item.label for item in app.expander} >= {"Level 1 · Preserved original-file report", "Level 1 · Reviewed import-copy report", "Saved repair receipt"}


def test_normalized_plot_remains_finite_for_extreme_recorded_values():
    import math
    from frib_ds.dashboard.event_view import signal_figure
    signal={"name":"voltage","unit":"V","timestamps_s":[0,1,2,3],
            "values":[-1e308,1e308,-1e308,1e308]}
    figure=signal_figure([signal],{"voltage":"Voltage"},(0,3),normalize=True)
    assert all(math.isfinite(value) for value in figure.data[0].y if value is not None)
    assert list(figure.data[0].y)==[-1,1,-1,1]
