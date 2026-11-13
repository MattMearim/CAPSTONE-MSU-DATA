"""Progressive evidence views retain real data, human choices and source detail."""
from __future__ import annotations

import copy
import json

import pytest
from streamlit.testing.v1 import AppTest

from test_dashboard_ui import Upload, backend, open_page, st


def mixed_event():
    return {
        "event_id": "MIXED-UI",
        "metadata": {"dataset_name": "Review capture"},
        "signals": [
            {"name": "pressure", "unit": "Pa", "timestamps_s": [0, 1, 2], "values": [1000, 2000, 3000]},
            {"name": "temperature", "unit": "K", "timestamps_s": [0, 1, 2], "values": [293, 294, 295]},
        ],
        "states": [
            {"name": "mode", "timestamp_s": 0, "value": "Ready"},
            {"name": "mode", "timestamp_s": 2, "value": "Running"},
        ],
        "logs": [
            {"timestamp_s": 0, "level": "INFO", "source": "shift", "message": "Capture opened"},
            {"timestamp_s": 1, "level": "WARNING", "source": "operator", "message": "Pressure noted <check>"},
            {"timestamp_s": 2, "level": "INFO", "source": "shift", "message": "Capture complete"},
        ],
    }


def explorer(event=None):
    source = "import json\nfrom frib_ds.dashboard.event_view import render_event_explorer\n"
    source += f"render_event_explorer(json.loads({json.dumps(event or mixed_event())!r}), prefix='simple')"
    return AppTest.from_string(source, default_timeout=15).run()


def plot(app):
    return json.loads(app.get("plotly_chart")[0].proto.spec)


def expander(app, label):
    return next(item for item in app.expander if item.label == label)


def test_only_active_evidence_kind_renders_and_source_details_stay_collapsed():
    app = explorer()
    assert not app.exception
    control = app.segmented_control(key="view_simple_MIXED-UI_kind")
    assert control.value == "Signals"
    assert len(app.get("plotly_chart")) == 1
    assert not any(item.label == "Search recorded notes" for item in app.text_input)
    assert plot(app)["layout"]["yaxis"]["title"]["text"].endswith("(Pa)")
    assert plot(app)["layout"]["yaxis2"]["title"]["text"].endswith("(K)")
    assert expander(app, "Time range").proto.expanded is False
    assert expander(app, "Chart title and display labels").proto.expanded is False
    control.set_value("States").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert plot(app)["data"][0]["y"] == ["Ready", "Running"]
    assert not any(item.label == "Visible numeric channels" for item in app.multiselect)
    source = expander(app, "Recorded values · mode")
    assert source.proto.expanded is False
    assert len(source.dataframe) == 1
    assert source.dataframe[0].value["value"].tolist() == ["Ready", "Running"]


def test_notes_are_literal_searchable_cards_with_optional_full_rows():
    app = explorer()
    app.segmented_control(key="view_simple_MIXED-UI_kind").set_value("Notes").run()
    assert not app.exception
    assert [item.value for item in app.text] == ["Capture opened", "Pressure noted <check>", "Capture complete"]
    assert expander(app, "Notes on the timeline").proto.expanded is False
    assert expander(app, "All matching note rows").proto.expanded is False
    app.text_input(key="view_simple_MIXED-UI_log_search").set_value("operator").run()
    assert [item.value for item in app.text] == ["Pressure noted <check>"]
    app.multiselect(key="view_simple_MIXED-UI_log_levels").set_value(["INFO"]).run()
    assert not app.text
    assert any("No notes match" in item.value for item in app.info)
    assert not app.exception


def test_display_choices_survive_evidence_switches():
    app = explorer()
    app.multiselect(key="view_simple_MIXED-UI_signals").set_value(["pressure"]).run()
    app.text_input(key="view_simple_MIXED-UI_label_pressure").set_value("Supply pressure").run()
    app.text_input(key="view_simple_MIXED-UI_title").set_value("Reviewed capture").run()
    app.segmented_control(key="view_simple_MIXED-UI_kind").set_value("Notes").run()
    app.text_input(key="view_simple_MIXED-UI_log_search").set_value("operator").run()
    app.segmented_control(key="view_simple_MIXED-UI_kind").set_value("Signals").run()
    assert app.multiselect(key="view_simple_MIXED-UI_signals").value == ["pressure"]
    assert app.text_input(key="view_simple_MIXED-UI_label_pressure").value == "Supply pressure"
    assert plot(app)["layout"]["title"]["text"] == "Reviewed capture"
    app.segmented_control(key="view_simple_MIXED-UI_kind").set_value("Notes").run()
    assert app.text_input(key="view_simple_MIXED-UI_log_search").value == "operator"
    assert not app.exception


def test_narrative_view_has_clear_no_numeric_channels_and_bounded_note_cards():
    event = mixed_event()
    event["signals"] = []
    event["states"] = []
    event["logs"] = [dict(event["logs"][0], message=f"Source note {index}") for index in range(10)]
    original = copy.deepcopy(event)
    app = explorer(event)
    assert any("No numeric channels" in item.value for item in app.caption)
    assert len(app.text) == 6
    assert not app.segmented_control
    app.checkbox(key="view_simple_MIXED-UI_all_logs").check().run()
    assert len(app.text) == 10
    assert event == original
    assert not app.exception


def test_quality_status_is_visible_with_bounded_issue_cards_and_full_report_download():
    issues = [{"code": f"FLAG_{i}", "severity": "warning", "title": f"Check {i}", "message": "Recorded difference", "rows": [i + 2], "count": 1, "suggestion": "Review source context"} for i in range(6)]
    report = {"stage": "L1", "status": "review", "summary": {"error": 0, "warning": 6, "info": 0}, "issues": issues}
    source = "import json\nfrom frib_ds.dashboard.quality_ui import render_quality_report\n"
    source += f"render_quality_report(json.loads({json.dumps(report)!r}), 'simple_quality', heading='Original file quality', expanded=True)"
    app = AppTest.from_string(source).run()
    assert not app.exception
    assert any("Review required" in item.value and "quality-summary" in item.value for item in app.markdown)
    assert expander(app, "Original file quality").proto.expanded is False
    assert len(app.warning) == 3
    locations = [item for item in app.expander if item.label in {"Source locations", "Recording interval locations"}]
    assert locations and all(item.proto.expanded is False for item in locations)
    app.checkbox(key="simple_quality_all_issues").check().run()
    assert len(app.warning) == 6
    assert any("Source rows: 7" in item.value for item in app.caption)
    assert len(app.get("download_button")) == 1
    app.text_input(key="simple_quality_search").set_value("FLAG_4").run()
    assert len(app.warning) == 1 and "Check 4" in app.warning[0].value
    assert not app.exception


def test_tsv_import_keeps_source_and_mapping_tables_optional(backend, monkeypatch):
    upload = Upload("capture.tsv", b"time_s\tcavity_field\n0\t1\n", "text/tab-separated-values")
    types = []

    def uploader(*args, **kwargs):
        if kwargs.get("key") == "csv_import":
            types.append(kwargs["type"])
            return upload
        return None

    monkeypatch.setattr(st, "file_uploader", uploader)
    app = open_page("🧪 Create Dataset")
    assert not app.exception
    assert types and all("tsv" in value for value in types)
    for label in ["Original file preview", "All column mappings", "Content summary and import details"]:
        assert expander(app, label).proto.expanded is False
    assert len(expander(app, "All column mappings").dataframe) == 1
    assert any("1 measurements" in item.value for item in app.caption)
    assert any(button.label == "📥 Import dataset" and not button.disabled for button in app.button)
