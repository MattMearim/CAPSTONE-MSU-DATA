"""Native, keyboard-accessible choices for an explicit human review decision."""
from __future__ import annotations

import streamlit as st


DECISIONS = (
    ("approve", "Approve", ":material/check_circle:", "Keep this draft as reviewed knowledge after submitting."),
    ("correct", "Correct", ":material/edit:", "Edit the draft below, then submit your corrected version."),
    ("escalate", "Escalate", ":material/flag:", "Record a request for further review. This draft stays out of approved knowledge."),
)


def _select_decision(form_key: str, decision: str) -> None:
    """Choose an action without saving a review or acknowledging it for the user."""
    decision_key = f"{form_key}_decision"
    if st.session_state.get(decision_key) != decision:
        st.session_state[decision_key] = decision
        st.session_state[f"{form_key}_acknowledged"] = False


def render_decision_buttons(form_key: str) -> str:
    """Return a local choice; submission, identity and evidence checks stay separate."""
    decision_key = f"{form_key}_decision"
    if st.session_state.get(decision_key) not in {item[0] for item in DECISIONS}:
        st.session_state[decision_key] = "approve"
    selected = st.session_state[decision_key]
    with st.container(key="review_decision_controls"):
        st.markdown("#### Human decision")
        st.caption("Choose an action. Your decision is saved only when you submit below.")
        columns = st.columns(3)
        for column, (value, label, icon, description) in zip(columns, DECISIONS):
            with column:
                with st.container(key=f"{form_key}_choice_{value}"):
                    st.button(
                        f"✓ {label}" if value == selected else label,
                        icon=None if value == selected else icon,
                        key=f"{form_key}_select_{value}",
                        type="primary" if value == selected else "secondary",
                        width="stretch",
                        help=description,
                        on_click=_select_decision,
                        args=(form_key, value),
                    )
        label, description = next((label, description) for value, label, _, description in DECISIONS if value == selected)
        st.caption(f"{label} selected: {description}")
    return selected
