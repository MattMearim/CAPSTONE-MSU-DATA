"""Generating a review draft stays in its current case and review workspace."""
from __future__ import annotations

import copy
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import Response, backend, open_page

INVESTIGATE = "🔎 Investigate Event"
REVIEW = "✅ Review Results"
STEPS = ["1 · Your data", "2 · What changed", "3 · Related guidance", "4 · Review & save"]


@pytest.fixture
def draft_backend(backend, monkeypatch):
    old_post = requests.post
    backend["draft_failure"] = False
    backend["draft_count"] = 0

    def post(url, **kwargs):
        if urlsplit(url).path != "/events/RF-TEST/draft":
            return old_post(url, **kwargs)
        backend["posts"].append((urlsplit(url).path, copy.deepcopy(kwargs)))
        backend["draft_count"] += 1
        if backend["draft_failure"]:
            return Response({"detail": "The configured model is temporarily unavailable"}, 503)
        draft = copy.deepcopy(backend["draft"])
        draft.update(draft_id=f"DRAFT-NEW-{backend['draft_count']}", summary="Newly generated review draft")
        backend["draft"] = draft
        return Response(draft)

    monkeypatch.setattr(requests, "post", post)
    return backend


def open_review(page):
    app = open_page(page)
    if page == INVESTIGATE:
        # Use the real workflow callback, not a session key that might never
        # reach the browser's active tab.
        for _ in range(3):
            app.button(key="workflow_next").click().run()
    assert_review_location(app, page)
    return app


def investigation_tabs(app):
    return next(container for container in app.get("tab_container")
                if [tab.label for tab in container.tabs] == STEPS)


def assert_review_location(app, page):
    assert not app.exception
    assert app.radio(key="main_nav").value == page
    assert app.session_state["workflow_event_id"] == "RF-TEST"
    assert "Knowledge library" in app.button(key="workflow_next").label
    if page == INVESTIGATE:
        assert app.selectbox(key="investigate_event").value == "RF-TEST"
        assert app.session_state["investigation_tabs"] == STEPS[3]
        assert app.session_state["workflow_resume_tab"] == STEPS[3]
        emitted = investigation_tabs(app).proto.tab_container
        assert emitted.id
        assert emitted.default_tab_index == 3
    else:
        assert app.selectbox(key="review_event_select").value["event_id"] == "RF-TEST"


def assert_only_draft_requested(state, count=1):
    assert [path for path, _ in state["posts"]] == ["/events/RF-TEST/draft"] * count
    assert not state["deletes"]


@pytest.mark.parametrize("page,prefix", [(INVESTIGATE, "investigate"), (REVIEW, "review")])
def test_generate_draft_preserves_actual_review_view_and_case(draft_backend, page, prefix):
    app = open_review(page)
    draft_backend["posts"].clear()
    app.button(key=f"{prefix}_generate_RF-TEST").click().run()
    assert_review_location(app, page)
    assert app.session_state["draft_RF-TEST"]["draft_id"] == "DRAFT-NEW-1"
    assert any(item.value == "Newly generated review draft" for item in app.info)
    assert app.button(key=f"{prefix}_DRAFT-NEW-1_submit").disabled
    assert_only_draft_requested(draft_backend)
    # Editing a field causes another full Streamlit run. That must not reopen
    # Related guidance, repeat generation, or move a receipt above the tabs.
    app.text_input(key=f"{prefix}_question_RF-TEST").set_value("Focus on the changed field").run()
    assert_review_location(app, page)
    assert_only_draft_requested(draft_backend)
    assert not app.get("progress"), "Editing the focus must not insert a stale completion bar elsewhere"
    if page == INVESTIGATE:
        assert not investigation_tabs(app).tabs[2].get("progress")


@pytest.mark.parametrize("page,prefix", [(INVESTIGATE, "investigate"), (REVIEW, "review")])
def test_failed_generation_keeps_original_draft_and_review_location(draft_backend, page, prefix):
    app = open_review(page)
    original = copy.deepcopy(draft_backend["draft"])
    draft_backend["draft_failure"] = True
    draft_backend["posts"].clear()
    app.button(key=f"{prefix}_generate_RF-TEST").click().run()
    assert_review_location(app, page)
    assert any("configured model is temporarily unavailable" in item.value for item in app.error)
    assert app.session_state["draft_RF-TEST"] == original
    assert not any(item.proto.value == 100 for item in app.get("progress"))
    assert_only_draft_requested(draft_backend)
    app.text_input(key=f"{prefix}_question_RF-TEST").set_value("Try a narrower focus later").run()
    assert_review_location(app, page)
    assert_only_draft_requested(draft_backend)


def test_generate_progress_is_inside_review_not_related_guidance(draft_backend):
    app = open_review(INVESTIGATE)
    app.button(key="investigate_generate_RF-TEST").click().run()
    assert_review_location(app, INVESTIGATE)
    tabs = investigation_tabs(app)
    review_progress = tabs.tabs[3].get("progress")
    assert review_progress, "The draft task must show its progress where Generate was clicked"
    assert any(item.proto.value == 100 for item in review_progress)
    assert len(review_progress) == len(app.get("progress")), "No duplicate progress receipt belongs above the tabs"
    for other in tabs.tabs[:3]:
        assert not other.get("progress")
    app.run()
    assert_review_location(app, INVESTIGATE)
    # A later rerun must not insert an out-of-context completion block.
    assert not app.get("progress")
    assert_only_draft_requested(draft_backend)


def test_inactive_investigation_steps_do_not_render_generate_or_guidance_actions(draft_backend):
    app = open_page(INVESTIGATE)
    assert app.session_state["investigation_tabs"] == STEPS[0]
    keys = {button.key for button in app.button}
    assert "investigate_generate_RF-TEST" not in keys
    assert not any(button.label == "Ask the document assistant" for button in app.button)
    assert "/events/RF-TEST/draft" not in draft_backend["gets"]
    app.button(key="workflow_next").click().run()
    app.button(key="workflow_next").click().run()
    assert app.session_state["investigation_tabs"] == STEPS[2]
    assert not any(button.key == "investigate_generate_RF-TEST" for button in app.button)
    assert any(button.label == "Ask the document assistant" for button in app.button)
    assert not draft_backend["posts"]
