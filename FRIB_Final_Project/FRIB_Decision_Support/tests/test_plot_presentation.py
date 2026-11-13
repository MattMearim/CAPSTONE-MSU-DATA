"""Presentation retains scientific coordinates, units and actionable quality context."""
from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from frib_ds.dashboard.event_view import chart_config, signal_figure
from frib_ds.dashboard.quality_ui import quality_summary_html


def signals():
    return [{"name": "pressure", "unit": "Pa", "timestamps_s": [0, 1, 2, 3], "values": [10, 20, 30, 40]},
        {"name": "temperature", "unit": "K", "timestamps_s": [0, .5, 1, 1.5, 2, 2.5, 3], "values": [290, 291, 292, 293, 294, 295, 296]}]


def test_workbench_theme_preserves_native_grids_units_and_display_window():
    source = signals()
    before = copy.deepcopy(source)
    figure = signal_figure(source, {"pressure": "Vacuum pressure", "temperature": "Cavity temperature"}, (1, 2.5))
    assert source == before
    assert list(figure.data[0].x) == [1, 2]
    assert list(figure.data[0].y) == [20, 30]
    assert list(figure.data[1].x) == [1, 1.5, 2, 2.5]
    assert "Pa" in figure.layout.yaxis.title.text
    assert "K" in figure.layout.yaxis2.title.text
    assert list(figure.layout.xaxis.range) == [1, 2.5]
    assert list(figure.layout.xaxis2.range) == [1, 2.5]
    assert figure.layout.xaxis2.title.text == "Elapsed time (s)"
    assert figure.layout.paper_bgcolor in {"white", "#ffffff", "#FFFFFF"}
    assert figure.layout.plot_bgcolor in {"white", "#ffffff", "#FFFFFF"}
    assert figure.layout.hovermode == "x unified"


def test_flags_have_severity_colors_and_text_without_changing_values():
    source = signals()[:1]
    report = {"issues": [
        {"code": "HIGH", "title": "Above declared bound", "column": "pressure", "severity": "error", "timestamps_s": [1]},
        {"code": "CHANGE", "title": "Possible real transition", "column": "pressure", "severity": "warning", "timestamps_s": [2]},
    ]}
    figure = signal_figure(source, {"pressure": "Pressure"}, (0, 3), quality_report=report)
    assert list(figure.data[0].y) == [10, 20, 30, 40]
    flags = figure.data[1]
    assert list(flags.x) == [1, 2]
    assert list(flags.y) == [20, 30]
    assert list(flags.marker.color) == ["#b4232c", "#b77913"]
    assert list(flags.text) == ["Above declared bound", "Possible real transition"]


def test_chart_toolbar_supports_export_without_implicit_scroll_zoom():
    config = chart_config("capture_pressure")
    assert config["toImageButtonOptions"]["format"] == "png"
    assert config["toImageButtonOptions"]["filename"] == "capture_pressure"
    assert config["scrollZoom"] is False
    assert config["displaylogo"] is False


def test_compact_summary_has_explicit_text_counts_and_escapes_report_labels():
    html = quality_summary_html({"stage": "L2<script>", "status": "blocked", "summary": {"error": 2, "warning": 3, "info": 1}})
    assert "Blocked" in html and "Errors" in html and "Warnings" in html and "Notes" in html
    assert "<strong>2</strong>" in html and "<strong>3</strong>" in html
    assert "<script>" not in html and "L2&lt;script&gt;" in html


def test_quality_details_expose_gap_interval_and_preserve_source_basis():
    report = {"stage": "L1", "status": "review", "summary": {"error": 0, "warning": 1, "info": 0},
        "location_basis": "reviewed_copy_rows", "issues": [{"code": "RECORDING_GAP", "severity": "warning",
            "title": "Review recording interval", "message": "A real transition remains possible.", "column": "pressure", "rows": [4],
            "timestamps_s": [8], "count": 1, "suggestion": "Compare the preserved source capture.", "repair": None,
            "intervals": [{"start_s": 2, "end_s": 8, "observed_interval_s": 6, "expected_interval_s": 1, "estimated_missing_samples": 5}]}], "unit_suggestions": []}
    script = "from frib_ds.dashboard.quality_ui import render_quality_report\nimport json\n"
    script += f"render_quality_report(json.loads({json.dumps(json.dumps(report))}), 'fixture', expanded=True)\n"
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert any("real transition" in item.value for item in app.warning)
    assert any("Reviewed-copy rows: 4" in item.value for item in app.caption)
    assert any("repair receipt records the original source rows" in item.value for item in app.caption)
    assert any(item.label == "Recording interval locations" for item in app.expander)
    assert app.dataframe[0].value.iloc[0]["Start (s)"] == 2
    assert app.dataframe[0].value.iloc[0]["End (s)"] == 8
    assert any(item.label == "Download quality report (JSON)" for item in app.get("download_button"))
