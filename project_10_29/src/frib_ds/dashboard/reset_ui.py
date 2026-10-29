"""Explicit project reset controls; the backend owns deletion and its receipt."""
from __future__ import annotations

import streamlit as st


COUNT_LABELS = {
    "events": "Datasets",
    "analyses": "Analyses",
    "drafts": "Drafts",
    "reviews": "Human reviews",
    "knowledge": "Knowledge records",
    "documents": "Documents",
    "document_chunks": "Document excerpts",
    "retrieval_vectors": "Search vectors",
    "event_files": "Event attachments",
    "stored_files": "Stored files",
    "audit_entries": "Audit entries",
}


def upload_widget_key(base: str) -> str:
    """Give file uploaders a fresh browser identity after a successful reset."""
    generation = st.session_state.get("project_reset_generation", 0)
    return f"{base}_reset_{generation}" if generation else base


def _submit_reset(api_post, friendly_error):
    # This callback runs before the next script render, allowing navigation and
    # already-created widget state to be replaced safely on success.
    if not st.session_state.get("project_reset_acknowledged") or st.session_state.get("project_reset_confirmation") != "RESET":
        st.session_state["project_reset_error"] = "Check the deletion acknowledgement and type RESET exactly."
        return
    try:
        receipt = api_post("/system/reset", {"confirmation": "RESET"})
        if not isinstance(receipt, dict) or receipt.get("reset") is not True:
            raise ValueError("The backend did not confirm the reset. Refresh the data counts before retrying.")
    except Exception as exc:
        st.session_state["project_reset_error"] = friendly_error(exc)
        return
    generation = st.session_state.get("project_reset_generation", 0) + 1
    for key in list(st.session_state):
        del st.session_state[key]
    st.cache_data.clear()
    st.session_state["project_reset_generation"] = generation
    st.session_state["main_nav"] = "🏠 Home"
    st.session_state["project_reset_receipt"] = receipt


def sidebar_project_reset(api_get, api_post, friendly_error):
    with st.expander("Reset project data"):
        st.warning("Permanently delete saved datasets, original uploads and attachments, documents and search indexes, analyses, drafts, reviews and knowledge from this project.")
        st.caption("Application code, configuration and bundled sample files remain. A minimal reset audit receipt is retained. Refresh other open dashboard sessions after resetting.")
        counts = None
        try:
            data = api_get("/system/data")
            counts = data["counts"]
            if not isinstance(counts, dict):
                raise ValueError("Data counts were not returned by the backend.")
            for key, label in COUNT_LABELS.items():
                if key in counts:
                    st.write(f"{label}: {counts[key]:,}")
        except Exception as exc:
            st.caption(f"Data counts unavailable: {friendly_error(exc)}")
        if counts is not None and not any(value for key, value in counts.items() if key != "audit_entries"):
            st.info("Project data is already empty.")
        st.checkbox("I understand that this permanently deletes the project data listed above.", key="project_reset_acknowledged")
        confirmation = st.text_input("Type RESET to confirm", key="project_reset_confirmation", autocomplete="off")
        allowed = counts is not None and st.session_state.get("project_reset_acknowledged", False) and confirmation == "RESET"
        st.button("Reset project data", key="project_reset_submit", disabled=not allowed,
            on_click=_submit_reset, args=(api_post, friendly_error), use_container_width=True)
        if st.session_state.get("project_reset_error"):
            st.error(f"Could not reset project data: {st.session_state['project_reset_error']}")
        if st.button("Refresh data counts", key="project_reset_refresh", use_container_width=True):
            st.rerun()


def show_reset_receipt():
    receipt = st.session_state.pop("project_reset_receipt", None)
    if receipt:
        st.success("Project data reset. Saved datasets, files, analyses and knowledge were cleared. The workspace is ready for new data.")
        with st.expander("Reset receipt", expanded=False):
            st.json(receipt)
