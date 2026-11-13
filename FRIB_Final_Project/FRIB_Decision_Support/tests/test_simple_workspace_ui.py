"""Exercise the card entry points and explicit Test Lab write boundaries."""
import json
from pathlib import Path

import pytest

from test_dashboard_ui import backend, open_page
from test_workbench_ui import workbench_backend, overview
from frib_ds.dashboard import test_lab_ui


@pytest.fixture
def bundled_lab(tmp_path, monkeypatch):
    datasets = tmp_path / "sample_data/test_lab"
    procedures = tmp_path / "sample_docs/test_lab"
    datasets.mkdir(parents=True)
    procedures.mkdir(parents=True)
    (datasets / "example.csv").write_text("time_s,field\n0,1\n1,0.5\n", encoding="utf-8")
    for name in ("approved.md", "draft.md"):
        (procedures / name).write_text("# Fictional procedure\nCheck the recorded field trace.\n", encoding="utf-8")
    manifest = {"datasets": [{"id": "case", "title": "Mixed evidence", "path": "sample_data/test_lab/example.csv",
        "filename": "example.csv", "format": "csv", "import_kind": "mixed", "options": {"event_id": "RF-TEST"},
        "expected_outcome": "Field changes are visible.", "steps": ["Preview", "Inspect units"]}],
        "procedures": [{"id": name, "title": name.title(), "path": f"sample_docs/test_lab/{name}.md",
            "filename": f"{name}.md", "version": "Rev 1", "approved": name == "approved"} for name in ("approved", "draft")],
        "walkthrough": ["Import evidence", "Run analysis", "Review the draft"]}
    (datasets / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(test_lab_ui, "project_root", lambda: tmp_path)
    return tmp_path, manifest


def test_dataset_card_opens_its_actual_identifier(workbench_backend):
    app = overview()
    app.button(key="overview_card_MECH-SECOND").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "🔎 Investigate Event"
    assert app.selectbox(key="investigate_event").value == "MECH-SECOND"


def test_lab_browsing_and_validated_preview_do_not_save(backend, bundled_lab):
    app = open_page("🧰 Test Lab")
    assert not app.exception and backend["posts"] == []
    app.button(key="lab_preview_case").click().run()
    assert not app.exception
    assert [path for path, _ in backend["posts"]] == ["/ingestion/preview"]
    assert backend["posts"][0][1]["data"]["validate"] == "true"
    assert not app.button(key="lab_save_case").disabled
    app.button(key="lab_save_case").click().run()
    assert not app.exception
    assert [path for path, _ in backend["posts"]] == ["/ingestion/preview", "/ingestion/import"]
    app.button(key="lab_open_case").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "🔎 Investigate Event"


def test_invalid_lab_preview_cannot_be_saved(backend, bundled_lab):
    backend["validation_errors"] = ["Invalid numeric cell at row 3."]
    app = open_page("🧰 Test Lab")
    app.button(key="lab_preview_case").click().run()
    assert not app.exception
    assert not any(button.key == "lab_save_case" for button in app.button)
    assert any("blocked" in warning.value for warning in app.warning)
    assert all(path == "/ingestion/preview" for path, _ in backend["posts"])


def procedure_view(app):
    app.segmented_control(key="test_lab_view").set_value("Procedures")
    app.run()
    assert not app.exception
    return app


def test_lab_approved_procedure_requires_explicit_checkbox(backend, bundled_lab):
    app = procedure_view(open_page("🧰 Test Lab"))
    assert app.button(key="lab_add_procedure_approved").disabled
    assert backend["posts"] == []
    app.session_state["rag_RF-TEST"] = {"answer": "Previous library result"}
    app.session_state["corpus_answer"] = {"answer": "Previous library result"}
    app.checkbox(key="lab_approve_approved").check().run()
    app.button(key="lab_add_procedure_approved").click().run()
    assert not app.exception
    assert backend["posts"][-1][0] == "/documents/index"
    assert backend["posts"][-1][1]["data"]["approved"] == "true"
    assert "rag_RF-TEST" not in app.session_state
    assert "corpus_answer" not in app.session_state


def test_lab_draft_remains_unapproved_on_import(backend, bundled_lab):
    app = procedure_view(open_page("🧰 Test Lab"))
    app.selectbox(key="lab_procedure").set_value("draft").run()
    assert not app.button(key="lab_add_procedure_draft").disabled
    app.button(key="lab_add_procedure_draft").click().run()
    assert not app.exception
    assert backend["posts"][-1][1]["data"]["approved"] == "false"


def test_lab_bundle_retains_source_files_and_rejects_escape(bundled_lab):
    import io
    import zipfile
    project, manifest = bundled_lab
    with zipfile.ZipFile(io.BytesIO(test_lab_ui.bundle_examples(project, manifest))) as archive:
        assert json.loads(archive.read("sample_data/test_lab/manifest.json")) == manifest
        assert archive.read("sample_data/test_lab/example.csv") == (project / "sample_data/test_lab/example.csv").read_bytes()
        assert "sample_docs/test_lab/approved.md" in archive.namelist()
    # Traversal is rejected before resolving or reading any fixture path.
    with pytest.raises(ValueError, match="plain relative fixture path"):
        test_lab_ui.lab_file(project, "../outside.csv")

