"""Review choices remain local until an acknowledged named human submits."""
from __future__ import annotations

import pytest

from test_dashboard_ui import backend, open_page


FORM = "review_DRAFT-TEST"


def test_review_choices_are_native_buttons_with_a_visible_selected_state(backend):
    app = open_page("✅ Review Results")
    assert app.button(key=f"{FORM}_select_approve").label == "✓ Approve"
    assert app.button(key=f"{FORM}_select_approve").proto.type == "primary"
    assert app.button(key=f"{FORM}_select_correct").proto.type == "secondary"
    assert app.button(key=f"{FORM}_select_escalate").proto.type == "secondary"
    assert not any(item.key == f"{FORM}_decision" for item in app.radio)
    assert any("Approve selected:" in item.value for item in app.caption)
    assert app.button(key=f"{FORM}_submit").disabled
    assert not backend["posts"]


@pytest.mark.parametrize("decision", ["approve", "correct", "escalate"])
def test_choosing_a_decision_does_not_submit_or_change_saved_records(backend, decision):
    app = open_page("✅ Review Results")
    app.button(key=f"{FORM}_select_{decision}").click().run()
    assert not app.exception
    assert app.session_state[f"{FORM}_decision"] == decision
    assert app.button(key=f"{FORM}_select_{decision}").label.startswith("✓ ")
    assert app.button(key=f"{FORM}_select_{decision}").proto.type == "primary"
    assert any(item.key == f"{FORM}_summary" for item in app.text_area) == (decision == "correct")
    assert backend["draft"]["status"] == "draft"
    assert not backend["posts"]


def test_changing_decision_requires_fresh_acknowledgement_and_preserves_reviewer(backend):
    app = open_page("✅ Review Results")
    app.text_input(key=f"{FORM}_reviewer").set_value("Jane Smith, RF engineer").run()
    app.checkbox(key=f"{FORM}_acknowledged").check().run()
    assert not app.button(key=f"{FORM}_submit").disabled
    app.button(key=f"{FORM}_select_escalate").click().run()
    assert not app.exception
    assert app.text_input(key=f"{FORM}_reviewer").value == "Jane Smith, RF engineer"
    assert not app.checkbox(key=f"{FORM}_acknowledged").value
    assert app.button(key=f"{FORM}_submit").disabled
    assert not backend["posts"]


def test_escalate_is_recorded_only_after_explicit_human_submission(backend):
    app = open_page("✅ Review Results")
    app.button(key=f"{FORM}_select_escalate").click().run()
    app.text_input(key=f"{FORM}_reviewer").set_value("Jane Smith, RF engineer").run()
    app.text_area(key=f"{FORM}_comments").set_value("Request a second review of the field trace.")
    app.checkbox(key=f"{FORM}_acknowledged").check().run()
    assert not backend["posts"]
    app.button(key=f"{FORM}_submit").click().run()
    assert not app.exception
    review = next(kwargs["json"] for path, kwargs in backend["posts"] if path.endswith("/review"))
    assert review == {"decision": "escalate", "reviewer": "Jane Smith, RF engineer", "comments": "Request a second review of the field trace.", "corrected_draft": None}
    assert backend["draft"]["status"] == "escalated"
    assert any("Escalation recorded" in item.value for item in app.success)


def test_correct_still_requires_a_nonempty_summary_before_submission(backend):
    app = open_page("✅ Review Results")
    app.button(key=f"{FORM}_select_correct").click().run()
    app.text_area(key=f"{FORM}_summary").set_value("   ")
    app.text_input(key=f"{FORM}_reviewer").set_value("Jane Smith, RF engineer")
    app.checkbox(key=f"{FORM}_acknowledged").check().run()
    assert not app.exception
    assert app.button(key=f"{FORM}_submit").disabled
    assert not backend["posts"]
