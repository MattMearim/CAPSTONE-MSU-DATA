"""Exercise citation selection with Streamlit's real rerun and callback behavior."""
from __future__ import annotations

import copy

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from frib_ds.dashboard.citation_ui import passage_html


RESPONSE = {
    "mode": "llm", "grounded": True,
    "answer": "## What changed\n\nPressure increased [S1].\n\nCompare the next reading [S2].",
    "evidence": ["Measured pressure increased from 1 to 2 Pa."],
    "sources": [
        {"label": "S1", "title": "Pressure response", "document_id": "DOC-aaaaaaaaaa", "chunk_id": "C1", "version": "3", "page": 2, "section": "First assessment", "excerpt": "Review pressure before assigning a cause."},
        {"label": "S2", "title": "Follow-up procedure", "document_id": "DOC-bbbbbbbbbb", "chunk_id": "C2", "version": "5", "page": 8, "section": "Trend review", "excerpt": "Compare the next reading with the baseline."},
    ],
}


SCRIPT = '''
import streamlit as st
from frib_ds.dashboard.citation_ui import render_rag_response
def get(path):
    st.session_state["calls"].append(("get", path))
    if st.session_state.get("offline"):
        raise RuntimeError("offline")
    return [{"document_id": "DOC-bbbbbbbbbb", "filename": "../trend.pdf"}]
def download(path):
    st.session_state["calls"].append(("download", path))
    if st.session_state.get("offline"):
        raise RuntimeError("offline")
    return b"original file"
render_rag_response(st.session_state["response"], key_prefix="answer", api_get=get, api_download=download)
'''


def render(response=None):
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["response"] = copy.deepcopy(RESPONSE if response is None else response)
    app.session_state["calls"] = []
    return app.run()


def button(app, label, *, source=False):
    return next(item for item in app.button if item.label == label and (not source or "_source_" in item.key))


def text(app):
    return "\n".join(item.value for item in app.markdown)


def test_adjacent_citation_selects_exact_source_without_retrieval_or_model_calls():
    original = copy.deepcopy(RESPONSE)
    app = render()
    assert not app.exception
    assert "Review pressure before assigning" not in text(app)
    assert "Compare the next reading with the baseline." not in text(app)
    assert all(item.label in {"S1", "S2"} for item in app.button)
    button(app, "S2").click().run()
    assert not app.exception
    assert "Compare the next reading with the baseline." in text(app)
    assert "Review pressure before assigning" not in text(app)
    assert any("Revision 5 · Page 8" in item.value for item in app.caption)
    assert any("Section: Trend review" in item.value for item in app.caption)
    assert app.session_state["calls"] == []
    assert app.session_state["response"] == original
    app.run()
    assert "Compare the next reading with the baseline." in text(app)
    assert app.session_state["calls"] == []


def test_source_picker_and_response_change_reset_stale_source_and_downloads():
    app = render()
    button(app, "S2", source=True).click().run()
    button(app, "Prepare original document").click().run()
    assert len(app.get("download_button")) == 1
    replacement = copy.deepcopy(RESPONSE)
    replacement.update(answer="A different answer [S1].", sources=[{**RESPONSE["sources"][0], "excerpt": "A new saved passage."}])
    app.session_state["response"] = replacement
    app.run()
    assert not app.exception
    assert "A new saved passage." not in text(app)
    assert app.session_state["answer_citation_state"]["selected"] is None
    button(app, "S1", source=True).click().run()
    assert "A new saved passage." in text(app)
    assert "Compare the next reading with the baseline." not in text(app)
    assert not app.get("download_button")
    assert not app.session_state["answer_citation_state"]["downloads"]


def test_original_document_is_explicit_cached_and_safe_filename():
    app = render()
    button(app, "S2", source=True).click().run()
    assert app.session_state["calls"] == []
    button(app, "Prepare original document").click().run()
    assert not app.exception
    assert app.session_state["calls"] == [("get", "/documents"), ("download", "/documents/DOC-bbbbbbbbbb/download")]
    cached = app.session_state["answer_citation_state"]["downloads"]["DOC-bbbbbbbbbb"]
    assert cached == {"data": b"original file", "filename": "trend.pdf"}
    button(app, "S1", source=True).click().run()
    button(app, "S2", source=True).click().run()
    assert len(app.get("download_button")) == 1
    assert len(app.session_state["calls"]) == 2


def test_missing_source_citation_is_explicit_and_never_fabricated():
    app = render({"mode": "llm", "answer": "An unsupported instruction [S99].", "sources": [], "grounded": False})
    assert not app.exception
    assert any("Source excerpt unavailable for [S99]" in item.value for item in app.warning)
    assert any("No approved document supports" in item.value for item in app.info)
    assert not app.button


@pytest.mark.parametrize("mode", ["extractive", "unavailable", "insufficient_context"])
def test_non_llm_modes_keep_context_without_ai_interpretation_label(mode):
    response = {**RESPONSE, "mode": mode, "error": "Model is offline" if mode == "unavailable" else None}
    app = render(response)
    assert not app.exception
    assert "AI interpretation · requires human review" not in text(app)
    assert any("Measured / derived evidence" in item.value for item in app.markdown)
    assert not any("may be shortened" in item.value for item in app.caption)
    button(app, "S1", source=True).click().run()
    assert any("may be shortened" in item.value for item in app.caption)


def test_excerpt_html_is_escaped_and_historical_source_metadata_is_optional():
    malicious = '<img src=x onerror="alert(1)"> & <script>bad()</script>'
    source = {"label": "S1", "title": "Historic procedure", "document_id": "../../etc/passwd", "excerpt": malicious}
    app = render({"mode": "extractive", "answer": "Historic passage [S1].", "sources": [None, source]})
    assert not app.exception
    button(app, "S1", source=True).click().run()
    assert "&lt;img" in text(app) and "&lt;script&gt;" in text(app)
    assert '<img src=' not in passage_html(malicious)
    assert any("Page not recorded" in item.value for item in app.caption)
    assert any("Original file link is unavailable" in item.value for item in app.caption)
    assert not any(item.label == "Prepare original document" for item in app.button)
    assert app.session_state["calls"] == []


def test_deleted_original_document_failure_keeps_saved_excerpt_visible():
    app = render()
    app.session_state["offline"] = True
    button(app, "S1", source=True).click().run()
    button(app, "Prepare original document").click().run()
    assert not app.exception
    assert any("original document is unavailable" in item.value for item in app.warning)
    assert "Review pressure before assigning" in text(app)
    assert not app.get("download_button")


def test_two_response_locations_have_independent_source_selection():
    app = AppTest.from_string('''
import streamlit as st
from frib_ds.dashboard.citation_ui import render_rag_response
render_rag_response(st.session_state["response"], key_prefix="first")
render_rag_response(st.session_state["response"], key_prefix="second")
''', default_timeout=15)
    app.session_state["response"] = copy.deepcopy(RESPONSE)
    app.run()
    next(item for item in app.button if item.label == "S2" and item.key.startswith("first_")).click().run()
    assert not app.exception
    assert app.session_state["first_citation_state"]["selected"] != app.session_state["second_citation_state"]["selected"]
    assert "Review pressure before assigning" not in text(app)
    assert "Compare the next reading with the baseline." in text(app)
    assert app.session_state["second_citation_state"]["selected"] is None


def test_bubbles_toggle_closed_without_network_or_record_changes():
    app = render()
    button(app, "S1", source=True).click().run()
    assert "Review pressure before assigning" in text(app)
    button(app, "S1", source=True).click().run()
    assert "Review pressure before assigning" not in text(app)
    assert app.session_state["answer_citation_state"]["selected"] is None
    assert not any(item.label == "Prepare original document" for item in app.button)
    assert app.session_state["calls"] == []
    assert app.session_state["response"] == RESPONSE


def test_sources_are_only_short_labels_until_opened():
    app = render()
    assert not app.exception
    assert "#### Sources" in text(app)
    assert all(item.label in {"S1", "S2"} for item in app.button)
    for hidden in ("Pressure response", "Follow-up procedure", "Retrieved procedure", "Document ID:"):
        assert hidden not in text(app)
    assert any(item.value.startswith("#### Measured / derived evidence") for item in app.markdown)
    assert any(item.value.startswith("#### AI interpretation") for item in app.markdown)


def test_draft_source_bubbles_preserve_all_metadata_without_constructing_links():
    app = AppTest.from_string('''
import streamlit as st
from frib_ds.dashboard.citation_ui import render_draft_sources
render_draft_sources(st.session_state["sources"], key_prefix="draft_TEST")
''', default_timeout=15)
    sources = ["DOC-1:CHUNK-1", {"document_id": "DOC-2", "section": "Alarms", "page": 3,
              "excerpt": "<script>not executable</script>", "version": "2"}, "https://unverified.example/procedure"]
    app.session_state["sources"] = copy.deepcopy(sources)
    app.run()
    assert not app.exception
    popovers = app.get("popover")
    assert [item.proto.popover.label for item in popovers] == ["S1", "S2", "S3"]
    assert not any(item.proto.popover.open for item in popovers)
    assert [item.value for item in app.text] == [sources[0], sources[2]]
    import json
    assert json.loads(app.json[0].value) == sources[1]
    assert app.session_state["sources"] == sources
    assert not app.button
    assert not any("<script>" in item.value for item in app.markdown)


def test_empty_draft_source_bubbles_are_explained_without_fake_citations():
    app = AppTest.from_string('''
from frib_ds.dashboard.citation_ui import render_draft_sources
render_draft_sources([], key_prefix="empty")
''', default_timeout=15).run()
    assert not app.exception
    assert not app.get("popover")
    assert any("No source references" in item.value for item in app.caption)
