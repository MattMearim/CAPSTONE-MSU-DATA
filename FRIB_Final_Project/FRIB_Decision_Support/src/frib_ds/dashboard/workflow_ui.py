"""Navigation between evidence, guidance and human review; never writes records."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

import streamlit as st
from frib_ds.dashboard.navigation import ADDITION_ITEMS, select_destination

HOME = "🏠 Home"
DATA = "🧪 Create Dataset"
DOCUMENTS = "📁 Files & Documents"
INVESTIGATE = "🔎 Investigate Event"
ASK = "💬 Ask Assistant"
REVIEW = "✅ Review Results"
KNOWLEDGE = "🧠 Engineering Wiki"
INVESTIGATION_STEPS = ("1 · Your data", "2 · What changed", "3 · Related guidance", "4 · Review & save")
CORE_PAGES = {HOME, DATA, DOCUMENTS, INVESTIGATE, ASK, REVIEW, KNOWLEDGE}


@dataclass(frozen=True)
class Destination:
    page: str
    label: str
    tab: str | None = None


def remember_event(event_id: str, label: str | None = None):
    if not event_id:
        return
    st.session_state["workflow_event_id"] = event_id
    st.session_state["workflow_event_label"] = label or event_id


def go_to(destination: Destination):
    """Widget callbacks run before the next render, preserving the chosen case."""
    event_id = st.session_state.get("workflow_event_id")
    if destination.page == INVESTIGATE:
        if event_id:
            st.session_state["investigate_event"] = event_id
        if destination.tab in INVESTIGATION_STEPS:
            st.session_state["investigation_tabs"] = destination.tab
    elif destination.page == REVIEW:
        st.session_state.pop("review_event_select", None)
    elif destination.page == ASK:
        st.session_state["assistant_event_context"] = event_id
    select_destination(st.session_state, destination.page)


def next_destinations(page: str, state):
    """Return useful Back/Next destinations without pretending work is complete."""
    if page == HOME:
        return None, Destination(DATA, "Next: Add your data"), "Start with a file, or use a fictional example from Try a demo."
    if page == DATA:
        return Destination(HOME, "Back: Home"), Destination(DOCUMENTS, "Next: Add procedures"), "Save the dataset above, then add the references you want the assistant to use."
    if page == DOCUMENTS:
        return Destination(DATA, "Back: Add data"), Destination(INVESTIGATE, "Next: Explore your data", INVESTIGATION_STEPS[0]), "Add and review your reference files, then explore the evidence."
    if page == INVESTIGATE:
        if not state.get("workflow_event_id"):
            return Destination(DOCUMENTS, "Back: Documents"), Destination(DATA, "Next: Add your data"), "Choose or import a dataset to begin an investigation."
        tab = state.get("investigation_tabs", INVESTIGATION_STEPS[0])
        index = INVESTIGATION_STEPS.index(tab) if tab in INVESTIGATION_STEPS else 0
        previous = Destination(DOCUMENTS, "Back: Documents") if index == 0 else Destination(INVESTIGATE, "Back: " + INVESTIGATION_STEPS[index - 1].split(" · ")[1], INVESTIGATION_STEPS[index - 1])
        following = Destination(KNOWLEDGE, "Next: Knowledge library") if index == 3 else Destination(INVESTIGATE, "Next: " + INVESTIGATION_STEPS[index + 1].split(" · ")[1], INVESTIGATION_STEPS[index + 1])
        hints = (
            "Check the selected dataset, its units and original files before exploring changes.",
            "Run analysis above to find changes, then compare them with your procedures.",
            "Check the cited passages beside the answer, then review the findings.",
            "Record your review above when ready. Next opens the library without approving a draft.",
        )
        return previous, following, hints[index]
    if page == ASK:
        return Destination(INVESTIGATE, "Back: Explore the evidence", INVESTIGATION_STEPS[2]), Destination(REVIEW, "Next: Review the findings") if state.get("workflow_event_id") else Destination(DOCUMENTS, "Next: Your documents"), "This page searches documents. For guidance about your measurements, use Related guidance in Explore an event."
    if page == REVIEW:
        return Destination(INVESTIGATE, "Back: Related guidance", INVESTIGATION_STEPS[2]), Destination(KNOWLEDGE, "Next: Knowledge library"), "Submit a human decision above when ready. Next does not approve or save a draft."
    if page == KNOWLEDGE:
        return Destination(REVIEW, "Back: Review findings"), Destination(HOME, "Next: Back to Home"), "Reviewed findings stay connected to their evidence and sources."
    if page == "🧰 Test Lab" or (page == ADDITION_ITEMS and state.get("addition_section") == "Try a new demo"):
        target = Destination(INVESTIGATE, "Next: Explore your example", INVESTIGATION_STEPS[0]) if state.get("workflow_event_id") else Destination(DATA, "Next: Add your data")
        return Destination(HOME, "Back: Home"), target, "Previewing an example does not save it. Save an example above to investigate it."
    resume = state.get("workflow_resume_page", HOME)
    if resume not in CORE_PAGES:
        resume = HOME
    resume_tab = state.get("workflow_resume_tab") if resume == INVESTIGATE else None
    return Destination(HOME, "Back: Home"), Destination(resume, "Next: Continue your work", resume_tab), "Return to the step you were working on."


def render_workflow_footer(page: str):
    if page in CORE_PAGES:
        st.session_state["workflow_resume_page"] = page
    if page == INVESTIGATE:
        st.session_state["workflow_resume_tab"] = st.session_state.get("investigation_tabs", INVESTIGATION_STEPS[0])
    previous, following, hint = next_destinations(page, st.session_state)
    with st.container(key="workflow_footer"):
        label = st.session_state.get("workflow_event_label")
        context = f'<span class="workflow-context">Current dataset: {escape(str(label))}</span>' if label else ""
        if page!=INVESTIGATE:
            st.markdown(f'<div class="workflow-footer-heading"><b>Your next step</b>{context}</div>', unsafe_allow_html=True)
            st.caption(hint)
        back, forward = st.columns([1, 1], gap="large")
        if previous:
            back.button("← " + previous.label, key="workflow_back", on_click=go_to, args=(previous,), width="stretch")
        forward.button(following.label + " →", key="workflow_next", type="primary", on_click=go_to, args=(following,), width="stretch")
