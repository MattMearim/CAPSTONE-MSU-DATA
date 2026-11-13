"""A compact Home-only introduction. Guidance and navigation never change records."""
from __future__ import annotations

from html import escape

import streamlit as st

from frib_ds.dashboard.design import NAV_LABELS, info_card

HOME = "🏠 Home"
STEPS = (
    {"title": "Meet your workspace", "page": HOME, "symbol": "✦",
     "summary": "Bring your data, trusted references and reviewed decisions together.",
     "instructions": ["Add data saves your measurements and notes while keeping the original files.", "Explore an event helps you see changes; Documents provides the references behind answers.", "A person reviews every draft before it becomes reusable knowledge."],
     "takeaway": "Browse these seven short introductions here on Home. Open a workspace page whenever you are ready to try it."},
    {"title": "Bring your first file", "page": "🧪 Create Dataset", "symbol": "↑",
     "summary": "Start with your own file or a fictional example, then check its preview before saving.",
     "instructions": ["Use Import data for CSV or TSV, Text & PDF for notes, or Event JSON for a saved event.", "For a collection, compress the folder in Finder and use Bulk import to upload its ZIP.", "Generate demo offers fictional examples. Saving or generating a dataset is always a separate action."],
     "takeaway": "Your original files are preserved. Choose the data tab that fits your source; no repair is selected for you."},
    {"title": "See what changed", "page": "🔎 Investigate Event", "symbol": "∿",
     "summary": "Explore measurements and notes, then look for meaningful changes with their context.",
     "instructions": ["Select a saved dataset and check its units, quality warnings and original files.", "In What changed, choose Run analysis and read the findings and timeline.", "Related guidance connects findings with sources. A pattern is evidence, not proof of a cause."],
     "takeaway": "The dataset you choose stays with you as you move from investigation to review."},
    {"title": "Build your reference shelf", "page": "📁 Files & Documents", "symbol": "≡",
     "summary": "Keep procedures and their revisions together so guidance has a source you can check.",
     "instructions": ["Add PDF, text or Markdown references and record the revision when known.", "Only approve a document when it is actually approved for that use.", "Unapproved files remain in the library but stay out of assistant answers."],
     "takeaway": "Try a demo includes clearly labeled fictional procedures for practice."},
    {"title": "Ask in your own words", "page": "💬 Ask Assistant", "symbol": "✧",
     "summary": "Ask a question and read the approved references that support the answer.",
     "instructions": ["Ask a question relevant to the references you have added.", "Choose Search approved documents, then compare the answer with its cited passages.", "If context is missing, add an appropriate approved reference or refine your question."],
     "takeaway": "Real local AI is configured in System status. Sources remain available alongside answers."},
    {"title": "Make the human decision", "page": "✅ Review Results", "symbol": "✓",
     "summary": "Check a draft against the evidence, then choose Approve, Correct or Escalate.",
     "instructions": ["Choose an analyzed event and generate a review draft when you are ready.", "Read the findings and references. Correct opens editing fields; Escalate requests further review.", "Enter your name and role, acknowledge responsibility, then choose Submit human decision."],
     "takeaway": "Selecting an action does not submit it. Only approved or corrected results enter reviewed knowledge."},
    {"title": "Keep what you learned", "page": "🧠 Engineering Wiki", "symbol": "↗",
     "summary": "Build a library of reviewed lessons that stay connected to their original evidence.",
     "instructions": ["Search reviewed records and read their sources, reviewer and history.", "Download a reviewed report when you need to revisit or share it.", "Connections shows a 3D web of saved relationships. Home search brings the whole workspace together."],
     "takeaway": "Return to Home whenever you want to replay this introduction. The tour never changes your saved records."},
)

STEP_LABELS = ("Welcome", "Add data", "Explore", "Documents", "Ask", "Review", "Library")
# Original local, decorative line art. It never represents live records.
ART_PATHS = (
    '<circle cx="60" cy="60" r="14"/><circle cx="27" cy="27" r="8"/><circle cx="93" cy="30" r="8"/><circle cx="92" cy="94" r="8"/><circle cx="26" cy="94" r="8"/><path d="m37 37 13 13m20 0 15-14M70 70l15 16M50 70 34 86"/>',
    '<path d="M38 20h29l17 17v63H38zM67 20v19h17M60 82V51m-11 11 11-11 11 11"/>',
    '<path d="M24 26v67h75M31 73l16-18 17 10 12-34 20 14"/><circle cx="76" cy="31" r="5"/>',
    '<rect x="30" y="20" width="59" height="79" rx="8"/><path d="M44 39h30M44 52h30M44 65h18M44 80l7 7 13-14"/>',
    '<path d="M30 25h60a9 9 0 0 1 9 9v41a9 9 0 0 1-9 9H57L32 99V84h-2a9 9 0 0 1-9-9V34a9 9 0 0 1 9-9Z"/><path d="M45 46c0-15 29-15 29 0 0 10-14 10-14 20M60 73v1"/>',
    '<path d="M60 18 91 30v28c0 23-31 42-31 42S29 81 29 58V30zM44 59l11 11 23-25"/>',
    '<path d="M23 29c13-6 26-6 37 2 11-8 24-8 37-2v63c-13-6-26-6-37 2-11-8-24-8-37-2zM60 31v63M35 45h12M35 58h12M72 45h12M72 58h12"/>',
)


def tutorial_steps_markup(index):
    """Visited stages describe overview navigation, not completed project work."""
    items = []
    for number, label in enumerate(STEP_LABELS):
        state = "current" if number == index else "visited" if number < index else "upcoming"
        current = ' aria-current="step"' if number == index else ""
        items.append(f'<li class="tutorial-stage {state}" aria-label="Step {number + 1}: {escape(label)}"{current}>'
                     f'<span class="tutorial-stage-number" aria-hidden="true">{number + 1}</span><span>{escape(label)}</span></li>')
    return '<ol class="tutorial-stages" aria-label="Guided tutorial stages">' + "".join(items) + '</ol>'


def tutorial_art_markup(index):
    return (f'<div class="tutorial-art tutorial-art-{index}" aria-hidden="true"><div class="tutorial-app-icon">'
            f'<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">{ART_PATHS[index]}</svg></div></div>')


def initialize_tutorial():
    st.session_state.setdefault("tutorial_status", "new")
    st.session_state.setdefault("tutorial_step", 0)
    if type(st.session_state["tutorial_step"]) is not int or not 0 <= st.session_state["tutorial_step"] < len(STEPS):
        st.session_state["tutorial_step"] = 0


def _open_step():
    """The overview lives on Home; changing stages does not open a task page."""
    st.session_state["main_nav"] = HOME


def start_tutorial():
    st.session_state.update(tutorial_status="active", tutorial_step=0)
    _open_step()


def reopen_tutorial():
    if st.session_state["tutorial_status"] in {"new", "complete", "skipped"}:
        start_tutorial()
    else:
        st.session_state["tutorial_status"] = "active"
        _open_step()


def move_tutorial(direction):
    st.session_state["tutorial_step"] = max(0, min(len(STEPS) - 1, st.session_state["tutorial_step"] + direction))
    _open_step()


def hide_tutorial():
    st.session_state["tutorial_status"] = "paused"


def skip_tutorial():
    st.session_state["tutorial_status"] = "skipped"


def finish_tutorial():
    st.session_state["tutorial_status"] = "complete"
    st.session_state["tutorial_completion_notice"] = True


def open_workspace():
    """Pause the Home overview and open the real page without performing a task."""
    index = st.session_state["tutorial_step"]
    if index == 1:
        st.session_state.setdefault("workspace_tabs", "Import data")
    elif index == 2:
        event_id = st.session_state.get("workflow_event_id") or st.session_state.get("investigate_event")
        if event_id:
            st.session_state["investigate_event"] = event_id
    elif index == 5:
        st.session_state.pop("review_event_select", None)
    hide_tutorial()
    st.session_state["main_nav"] = STEPS[index]["page"]


def render_welcome():
    if st.session_state.get("main_nav", HOME) != HOME or st.session_state["tutorial_status"] == "active":
        return
    status = st.session_state["tutorial_status"]
    paused = status == "paused"
    with st.container(border=True, key="panel_tutorial_welcome"):
        left, right = st.columns([3.5, 1.2], vertical_alignment="center", gap="medium")
        with left:
            title = "Pick up where you left off." if paused else "A little guidance to get started."
            detail = f'Step {st.session_state["tutorial_step"] + 1} of {len(STEPS)} · Your place is saved here on Home.' if paused else 'A short introduction to data, guidance and human review. Available here on Home, whenever you need it.'
            st.markdown('<div class="tutorial-invitation"><span class="tutorial-invitation-icon" aria-hidden="true">✦</span>'
                        f'<div><span class="tutorial-kicker">QUICK START</span><h3>{escape(title)}</h3><p>{escape(detail)}</p></div></div>', unsafe_allow_html=True)
        with right:
            if status == "new":
                st.button("Start tutorial", key="tutorial_start", type="primary", width="stretch", on_click=start_tutorial)
                st.button("Skip for now", key="tutorial_skip", width="stretch", on_click=skip_tutorial)
            else:
                st.button("Continue tutorial" if paused else "Replay tutorial", key="tutorial_reopen", type="primary", width="stretch", on_click=reopen_tutorial)
                if paused:
                    st.button("Start over", key="tutorial_restart", width="stretch", on_click=start_tutorial)


def render_active_tutorial(page):
    if page != HOME:
        if st.session_state["tutorial_status"] == "active":
            hide_tutorial()
        return
    if st.session_state.pop("tutorial_completion_notice", False):
        st.success("Tutorial complete. Explore the workspace when you are ready, or replay the introduction here on Home.")
    if st.session_state["tutorial_status"] != "active":
        return
    index = st.session_state["tutorial_step"]
    step = STEPS[index]
    st.markdown('<span class="frib-tutorial-active" aria-hidden="true"></span>', unsafe_allow_html=True)
    with st.container(border=True, key="panel_tutorial"):
        st.markdown(f'<div class="tutorial-progress-header"><span>QUICK TOUR</span><span>Step {index + 1} of {len(STEPS)} · Home</span></div>'
                    + tutorial_steps_markup(index), unsafe_allow_html=True)
        st.markdown('<div class="tutorial-summary">' + tutorial_art_markup(index)
                    + f'<div class="tutorial-heading"><h2>{escape(step["title"])}</h2><p>{escape(step["summary"])}</p></div></div>', unsafe_allow_html=True)
        with st.expander("How to try this step", expanded=False):
            for number, instruction in enumerate(step["instructions"], 1):
                st.markdown(f"{number}. {instruction}")
            st.caption(step["takeaway"])
            st.caption("The tutorial stays on Home. Open a workspace page to try a task, then return Home to continue.")
            st.button("Start over", key="tutorial_restart", on_click=start_tutorial)
        with st.container(key="tutorial_controls"):
            back, forward, workspace, hide = st.columns([1, 1.3, 1.8, 1], gap="small")
            back.button("Back", key="tutorial_back", disabled=index == 0, width="stretch", on_click=move_tutorial, args=(-1,))
            if index == len(STEPS) - 1:
                forward.button("Finish tutorial", key="tutorial_finish", type="primary", width="stretch", on_click=finish_tutorial)
            else:
                forward.button("Continue", key="tutorial_next", type="primary", width="stretch", on_click=move_tutorial, args=(1,))
            workspace.button("Explore Home" if index == 0 else f"Open {NAV_LABELS[step['page']]}", key="tutorial_open_workspace", width="stretch", on_click=open_workspace)
            hide.button("Pause", key="tutorial_hide", width="stretch", on_click=hide_tutorial)


def render_tutorial_help():
    with st.container(border=True, key="panel_tutorial_help"):
        info_card("Getting started", "The interactive tutorial is available on Home. You can read the complete written guide here.", "QUICK GUIDE", "✦")
        with st.expander("Read the complete beginner guide"):
            from pathlib import Path
            guide = Path(__file__).resolve().parents[3] / "docs/FIRST_STEPS.md"
            if guide.is_file():
                st.markdown(guide.read_text(encoding="utf-8"))
