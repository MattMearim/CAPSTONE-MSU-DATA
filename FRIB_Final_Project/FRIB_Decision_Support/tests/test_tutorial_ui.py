"""The optional first-use overview belongs to Home and never changes records."""
from __future__ import annotations

import copy

import pytest

from test_dashboard_ui import backend, select_page
from test_workbench_ui import overview, workbench_backend
from frib_ds.dashboard.navigation import ADDITION_ITEMS, LEGACY_SECTIONS


HOME = "🏠 Home"
TOUR_PAGES = [
    HOME,
    "🧪 Create Dataset",
    "🔎 Investigate Event",
    "📁 Files & Documents",
    "💬 Ask Assistant",
    "✅ Review Results",
    "🧠 Engineering Wiki",
]
OTHER_PAGES = [
    *TOUR_PAGES[1:], "🕸️ Connections", "🧰 Test Lab", "❓ Help",
    "⚙️ Settings", "🖥️ System & upgrades",
]


def button_keys(app):
    return {button.key for button in app.button if button.key}


def tutorial_button_keys(app):
    return {key for key in button_keys(app) if key.startswith("tutorial_") or key.startswith("help_tutorial_")}


def assert_tour_location(app, step):
    assert not app.exception
    assert app.session_state["tutorial_status"] == "active"
    assert app.session_state["tutorial_step"] == step
    assert app.radio(key="main_nav").value == HOME
    assert not any((button.key or "").startswith("tutorial_") for button in app.sidebar.button)


def assert_no_writes(backend):
    assert backend["posts"] == [], "Tutorial navigation must not create, analyze or approve records"
    assert backend["deletes"] == [], "Tutorial navigation must not delete evidence"


def start_tour():
    app = overview()
    app.button(key="tutorial_start").click().run()
    assert_tour_location(app, 0)
    return app


def test_first_session_offers_a_home_tour_without_starting_it_or_saving_data(workbench_backend, backend):
    app = overview()
    assert app.session_state["tutorial_status"] == "new"
    assert app.session_state["tutorial_step"] == 0
    assert tutorial_button_keys(app) == {"tutorial_start", "tutorial_skip"}
    assert not any((button.key or "").startswith("tutorial_") for button in app.sidebar.button)
    app.run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "new"
    assert_no_writes(backend)


def test_next_and_back_browse_the_overview_without_leaving_home(workbench_backend, backend):
    app = start_tour()
    assert app.button(key="tutorial_back").disabled
    for step in (1, 2):
        app.button(key="tutorial_next").click().run()
        assert_tour_location(app, step)
        app.run()
        assert_tour_location(app, step)
    for step in (1, 0):
        app.button(key="tutorial_back").click().run()
        assert_tour_location(app, step)
    assert "tutorial_use_my_file" not in button_keys(app)
    assert "tutorial_use_demo" not in button_keys(app)
    assert_no_writes(backend)


def test_skipping_remains_dismissed_until_the_home_invitation_reopens_the_tour(workbench_backend, backend):
    app = overview()
    app.button(key="tutorial_skip").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "skipped"
    assert app.radio(key="main_nav").value == HOME
    assert tutorial_button_keys(app) == {"tutorial_reopen"}
    app.run()
    assert tutorial_button_keys(app) == {"tutorial_reopen"}
    app.button(key="tutorial_reopen").click().run()
    assert_tour_location(app, 0)
    assert_no_writes(backend)


def test_paused_progress_survives_other_pages_and_resumes_only_from_home(workbench_backend, backend):
    app = start_tour()
    for _ in range(3):
        app.button(key="tutorial_next").click().run()
    assert_tour_location(app, 3)
    app.button(key="tutorial_hide").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == 3
    assert tutorial_button_keys(app) == {"tutorial_reopen", "tutorial_restart"}
    select_page(app, "❓ Help")
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == 3
    assert not tutorial_button_keys(app)
    app.radio(key="main_nav").set_value(HOME).run()
    assert tutorial_button_keys(app) == {"tutorial_reopen", "tutorial_restart"}
    app.button(key="tutorial_reopen").click().run()
    assert_tour_location(app, 3)
    assert_no_writes(backend)


@pytest.mark.parametrize("page", OTHER_PAGES)
def test_leaving_home_pauses_guidance_and_other_pages_have_no_tutorial_controls(workbench_backend, backend, page):
    app = start_tour()
    app.button(key="tutorial_next").click().run()
    select_page(app, page)
    assert not app.exception
    assert app.radio(key="main_nav").value == (ADDITION_ITEMS if page in LEGACY_SECTIONS else page)
    if page in LEGACY_SECTIONS:
        assert app.session_state["addition_section"] == LEGACY_SECTIONS[page]
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == 1
    assert not tutorial_button_keys(app)
    assert not any('<span class="frib-tutorial-active"' in item.value for item in app.markdown)
    app.radio(key="main_nav").set_value(HOME).run()
    assert not app.exception
    assert tutorial_button_keys(app) == {"tutorial_reopen", "tutorial_restart"}
    app.button(key="tutorial_reopen").click().run()
    assert_tour_location(app, 1)
    assert_no_writes(backend)


@pytest.mark.parametrize("step", range(1, len(TOUR_PAGES)))
def test_open_workspace_pauses_the_home_overview_and_only_navigates(workbench_backend, backend, step):
    app = start_tour()
    for _ in range(step):
        app.button(key="tutorial_next").click().run()
    assert_tour_location(app, step)
    app.button(key="tutorial_open_workspace").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == TOUR_PAGES[step]
    assert app.session_state["tutorial_status"] == "paused"
    assert app.session_state["tutorial_step"] == step
    assert not tutorial_button_keys(app)
    assert_no_writes(backend)


def test_complete_tour_covers_every_stage_on_home_without_changing_evidence(workbench_backend, backend):
    original_records = copy.deepcopy({
        "event": backend["event"], "draft": backend["draft"],
        "documents": backend["documents"], "events": workbench_backend["events"],
    })
    app = start_tour()
    for step in range(1, len(TOUR_PAGES)):
        app.button(key="tutorial_next").click().run()
        assert_tour_location(app, step)
    assert "tutorial_next" not in button_keys(app)
    app.button(key="tutorial_finish").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "complete"
    assert app.radio(key="main_nav").value == HOME
    assert tutorial_button_keys(app) == {"tutorial_reopen"}
    assert_no_writes(backend)
    assert {
        "event": backend["event"], "draft": backend["draft"],
        "documents": backend["documents"], "events": workbench_backend["events"],
    } == original_records


def test_completed_tour_replays_and_paused_tour_restarts_from_home(workbench_backend, backend):
    app = start_tour()
    for _ in range(len(TOUR_PAGES) - 1):
        app.button(key="tutorial_next").click().run()
    app.button(key="tutorial_finish").click().run()
    app.button(key="tutorial_reopen").click().run()
    assert_tour_location(app, 0)
    for _ in range(2):
        app.button(key="tutorial_next").click().run()
    assert_tour_location(app, 2)
    app.button(key="tutorial_hide").click().run()
    app.button(key="tutorial_restart").click().run()
    assert_tour_location(app, 0)
    assert_no_writes(backend)
