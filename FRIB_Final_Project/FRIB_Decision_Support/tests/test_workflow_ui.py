"""Guided navigation preserves evidence context without changing saved records."""
from __future__ import annotations

import pytest

from test_dashboard_ui import backend, select_page
from test_workbench_ui import overview, workbench_backend


HOME = "🏠 Home"
DATA = "🧪 Create Dataset"
DOCUMENTS = "📁 Files & Documents"
INVESTIGATE = "🔎 Investigate Event"
REVIEW = "✅ Review Results"
KNOWLEDGE = "🧠 Engineering Wiki"
STEPS = ["1 · Your data", "2 · What changed", "3 · Related guidance", "4 · Review & save"]


def assert_step(app, index):
    assert not app.exception
    assert app.radio(key="main_nav").value == INVESTIGATE
    assert app.session_state["investigation_tabs"] == STEPS[index]
    tabs = next(container for container in app.get("tab_container")
                if [tab.label for tab in container.tabs] == STEPS)
    # A stored session key alone does not guarantee the user sees the selected tab.
    assert tabs.proto.tab_container.id
    assert tabs.proto.tab_container.default_tab_index == index


def assert_no_writes(backend):
    assert backend["posts"] == [], "Navigation must not run analysis, generate, save or approve"
    assert backend["deletes"] == [], "Navigation must not delete evidence"


def test_next_guides_from_home_through_evidence_to_knowledge(workbench_backend, backend):
    app = overview()
    assert not any(button.key == "workflow_back" for button in app.button)
    for expected in (DATA, DOCUMENTS, INVESTIGATE):
        app.button(key="workflow_next").click().run()
        assert not app.exception
        assert app.radio(key="main_nav").value == expected
    assert_step(app, 0)
    selected = app.selectbox(key="investigate_event").value
    for index in range(1, 4):
        app.button(key="workflow_next").click().run()
        assert_step(app, index)
        assert app.selectbox(key="investigate_event").value == selected
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == KNOWLEDGE
    assert_no_writes(backend)


def test_back_reverses_investigation_steps_then_returns_to_documents(workbench_backend, backend):
    app = overview()
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    for _ in range(3):
        app.button(key="workflow_next").click().run()
    for index in (2, 1, 0):
        app.button(key="workflow_back").click().run()
        assert_step(app, index)
    for expected in (DOCUMENTS, DATA, HOME):
        app.button(key="workflow_back").click().run()
        assert not app.exception
        assert app.radio(key="main_nav").value == expected
    assert_no_writes(backend)


def test_investigation_without_datasets_offers_add_data(workbench_backend, backend):
    workbench_backend["events"] = []
    workbench_backend["total"] = 0
    app = overview()
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    assert not app.exception
    assert "Add your data" in app.button(key="workflow_next").label
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == DATA
    assert_no_writes(backend)


def test_changed_investigation_dataset_is_used_on_review_page(workbench_backend, backend):
    app = overview()
    app.radio(key="main_nav").set_value(REVIEW).run()
    # Simulate a previous review selection before the user switches investigations.
    assert app.selectbox(key="review_event_select").value["event_id"] == "RF-TEST"
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    app.selectbox(key="investigate_event").set_value("MECH-SECOND").run()
    app.radio(key="main_nav").set_value("💬 Ask Assistant").run()
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == REVIEW
    assert app.selectbox(key="review_event_select").value["event_id"] == "MECH-SECOND"
    app.button(key="workflow_back").click().run()
    assert_step(app, 2)
    assert app.selectbox(key="investigate_event").value == "MECH-SECOND"
    assert_no_writes(backend)


def test_switching_dataset_restarts_with_its_evidence(workbench_backend, backend):
    app = overview()
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    app.button(key="workflow_next").click().run()
    app.button(key="workflow_next").click().run()
    assert_step(app, 2)
    app.selectbox(key="investigate_event").set_value("MECH-SECOND").run()
    assert_step(app, 0)
    assert app.session_state["workflow_event_id"] == "MECH-SECOND"
    assert_no_writes(backend)


@pytest.mark.parametrize("page", ["❓ Help", "⚙️ Settings", "🖥️ System & upgrades"])
def test_auxiliary_page_continues_selected_investigation_step(workbench_backend, backend, page):
    app = overview()
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    app.selectbox(key="investigate_event").set_value("MECH-SECOND").run()
    app.button(key="workflow_next").click().run()
    assert_step(app, 1)
    select_page(app, page)
    assert not app.exception
    assert "Continue your work" in app.button(key="workflow_next").label
    app.button(key="workflow_next").click().run()
    assert_step(app, 1)
    assert app.selectbox(key="investigate_event").value == "MECH-SECOND"
    assert_no_writes(backend)


def test_review_next_opens_library_without_saving_human_decision(workbench_backend, backend):
    app = overview()
    app.radio(key="main_nav").set_value(REVIEW).run()
    assert app.button(key="review_DRAFT-TEST_submit").disabled
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == KNOWLEDGE
    assert backend["draft"]["status"] == "draft"
    assert_no_writes(backend)


def test_demo_next_without_a_saved_example_opens_add_data(workbench_backend, backend):
    workbench_backend["events"] = []
    workbench_backend["total"] = 0
    app = overview()
    select_page(app, "🧰 Test Lab")
    assert not app.exception
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == DATA
    assert_no_writes(backend)


def test_normal_home_next_pauses_the_overview_and_opens_add_data(workbench_backend, backend):
    app = overview()
    app.button(key="tutorial_start").click().run()
    app.button(key="tutorial_next").click().run()
    assert app.session_state["tutorial_status"] == "active"
    assert app.session_state["tutorial_step"] == 1
    assert app.radio(key="main_nav").value == HOME
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == 1
    assert app.radio(key="main_nav").value == DATA
    assert not any((button.key or "").startswith("tutorial_") for button in app.button)
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == DOCUMENTS
    assert app.session_state["tutorial_step"] == 1
    assert_no_writes(backend)


def test_normal_footer_keeps_its_route_after_the_home_overview_reaches_its_last_stage(workbench_backend, backend):
    app = overview()
    app.button(key="tutorial_start").click().run()
    for index in range(1, 7):
        app.button(key="tutorial_next").click().run()
        assert not app.exception
        assert app.session_state["tutorial_step"] == index
        assert app.radio(key="main_nav").value == HOME
        assert app.session_state["tutorial_status"] == "active"
    assert "Finish tutorial" not in app.button(key="workflow_next").label
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == 6
    assert app.radio(key="main_nav").value == DATA
    assert backend["draft"]["status"] == "draft"
    assert_no_writes(backend)


def test_paused_overview_does_not_change_auxiliary_page_continue_destination(workbench_backend, backend):
    app = overview()
    app.button(key="tutorial_start").click().run()
    for _ in range(3):
        app.button(key="tutorial_next").click().run()
    app.radio(key="main_nav").set_value(INVESTIGATE).run()
    app.selectbox(key="investigate_event").set_value("MECH-SECOND").run()
    app.button(key="workflow_next").click().run()
    assert_step(app, 1)
    select_page(app, "❓ Help")
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert not any((button.key or "").startswith(("tutorial_", "help_tutorial_")) for button in app.button)
    app.button(key="workflow_next").click().run()
    assert_step(app, 1)
    assert app.selectbox(key="investigate_event").value == "MECH-SECOND"
    assert app.session_state["tutorial_step"] == 3
    assert_no_writes(backend)
