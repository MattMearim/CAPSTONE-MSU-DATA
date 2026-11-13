"""Compact Home guidance is accessible and never changes saved evidence."""
from __future__ import annotations

import copy
from html.parser import HTMLParser

import pytest

from test_dashboard_ui import backend
from test_workbench_ui import overview, workbench_backend


STAGE_LABELS = ("Welcome", "Add data", "Explore", "Documents", "Ask", "Review", "Library")


class Markup(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, value):
        self.text.append(value)


def active_marker_is_rendered(app):
    return any(
        "frib-tutorial-active" in attributes.get("class", "").split()
        for item in app.markdown
        for _, attributes in Markup(item.value).elements
    )


def assert_no_writes(backend):
    assert backend["posts"] == [], "Tour actions must not save or approve records"
    assert backend["deletes"] == [], "Tour actions must not delete evidence"


@pytest.mark.parametrize("index", range(len(STAGE_LABELS)))
def test_stage_indicator_exposes_all_stages_and_one_accessible_current_stage(index):
    from frib_ds.dashboard.tutorial_ui import tutorial_steps_markup

    rendered = Markup(tutorial_steps_markup(index))
    assert any(tag == "ol" for tag, _ in rendered.elements)
    steps = [attributes for tag, attributes in rendered.elements if tag == "li"]
    assert len(steps) == len(STAGE_LABELS)
    current = [attributes for _, attributes in rendered.elements if attributes.get("aria-current") == "step"]
    assert len(current) == 1
    assert steps[index].get("aria-current") == "step"
    text = " ".join(rendered.text)
    positions = [text.index(label) for label in STAGE_LABELS]
    assert positions == sorted(positions)


@pytest.mark.parametrize("index", range(len(STAGE_LABELS)))
def test_stage_illustrations_are_decorative_and_have_no_remote_or_executable_content(index):
    from frib_ds.dashboard.tutorial_ui import tutorial_art_markup

    rendered = Markup(tutorial_art_markup(index))
    assert rendered.elements
    assert rendered.elements[0][1].get("aria-hidden") == "true"
    assert not any(tag in {"script", "iframe", "object", "embed"} for tag, _ in rendered.elements)
    for _, attributes in rendered.elements:
        assert not any(name.lower().startswith("on") for name in attributes)
        for name in ("href", "xlink:href", "src"):
            reference = attributes.get(name)
            assert not reference or reference.startswith("#"), "Tutorial art must use only local inline shapes"


def test_compact_card_marker_is_present_only_while_the_home_tour_is_active(workbench_backend, backend):
    app = overview()
    assert not active_marker_is_rendered(app)
    app.button(key="tutorial_start").click().run()
    assert not app.exception
    assert active_marker_is_rendered(app)
    app.button(key="tutorial_hide").click().run()
    assert not app.exception
    assert not active_marker_is_rendered(app)
    assert app.session_state["tutorial_status"] == "paused"
    app.button(key="tutorial_reopen").click().run()
    assert active_marker_is_rendered(app)
    for _ in range(len(STAGE_LABELS) - 1):
        app.button(key="tutorial_next").click().run()
        assert not app.exception
        assert active_marker_is_rendered(app)
    app.button(key="tutorial_finish").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "complete"
    assert not active_marker_is_rendered(app)
    assert_no_writes(backend)


def test_tour_keeps_the_users_reduced_motion_choice_through_pause_and_resume(workbench_backend, backend):
    app = overview()
    app.toggle(key="interface_motion").set_value(False).run()
    app.button(key="tutorial_start").click().run()
    app.button(key="tutorial_next").click().run()
    assert not app.exception
    assert app.toggle(key="interface_motion").value is False
    assert any('class="frib-motion-off"' in item.value for item in app.markdown)
    app.button(key="tutorial_hide").click().run()
    app.button(key="tutorial_reopen").click().run()
    assert not app.exception
    assert app.session_state["tutorial_step"] == 1
    assert app.toggle(key="interface_motion").value is False
    assert active_marker_is_rendered(app)
    assert_no_writes(backend)


@pytest.mark.parametrize("event_id", ["MECH-SECOND", "IMPORTED-OWN"])
def test_investigation_stage_keeps_the_current_event_instead_of_a_stale_demo(workbench_backend, backend, event_id):
    if event_id == "IMPORTED-OWN":
        imported = copy.deepcopy(backend["event"])
        imported["event_id"] = event_id
        imported["metadata"]["dataset_name"] = "My imported evidence"
        workbench_backend["events"].append(imported)
        workbench_backend["total"] += 1
    original_records = copy.deepcopy((workbench_backend["events"], backend["draft"], backend["documents"]))
    app = overview()
    app.radio(key="main_nav").set_value("🔎 Investigate Event").run()
    app.selectbox(key="investigate_event").set_value(event_id).run()
    assert app.session_state["workflow_event_id"] == event_id
    app.session_state["last_generated_event"] = copy.deepcopy(backend["event"])
    app.radio(key="main_nav").set_value("🏠 Home").run()
    app.button(key="tutorial_start").click().run()
    app.button(key="tutorial_next").click().run()
    app.button(key="tutorial_next").click().run()
    assert not app.exception
    assert app.session_state["tutorial_step"] == 2
    assert app.radio(key="main_nav").value == "🏠 Home"
    assert app.session_state["workflow_event_id"] == event_id
    app.button(key="tutorial_open_workspace").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert not active_marker_is_rendered(app)
    assert app.radio(key="main_nav").value == "🔎 Investigate Event"
    assert app.selectbox(key="investigate_event").value == event_id
    assert app.session_state["workflow_event_id"] == event_id
    assert (workbench_backend["events"], backend["draft"], backend["documents"]) == original_records
    assert_no_writes(backend)


def test_review_stage_follows_the_current_investigation_instead_of_an_old_review(workbench_backend, backend):
    app = overview()
    app.radio(key="main_nav").set_value("✅ Review Results").run()
    assert app.selectbox(key="review_event_select").value["event_id"] == "RF-TEST"
    app.radio(key="main_nav").set_value("🔎 Investigate Event").run()
    app.selectbox(key="investigate_event").set_value("MECH-SECOND").run()
    app.radio(key="main_nav").set_value("🏠 Home").run()
    app.button(key="tutorial_start").click().run()
    for _ in range(5):
        app.button(key="tutorial_next").click().run()
        assert not app.exception
    assert app.session_state["tutorial_step"] == 5
    assert app.radio(key="main_nav").value == "🏠 Home"
    app.button(key="tutorial_open_workspace").click().run()
    assert not app.exception
    assert app.session_state["tutorial_status"] == "paused"
    assert not active_marker_is_rendered(app)
    assert app.radio(key="main_nav").value == "✅ Review Results"
    assert app.selectbox(key="review_event_select").value["event_id"] == "MECH-SECOND"
    assert backend["draft"]["status"] == "draft"
    assert_no_writes(backend)
