"""Connections explore saved relationships without invoking AI or changing records."""
from __future__ import annotations

import copy
import re
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import Response, backend, open_page


CONNECTIONS = "🕸️ Connections"
EVENT = "event:RF-TEST"
DOCUMENT = "document:DOC-1"
FINDING = "finding:RF-TEST:0"
DRAFT = "draft:DRAFT-TEST"
KNOWLEDGE = "knowledge:KN-MOTOR"


GRAPH = {
    "nodes": [
        {"id": EVENT, "kind": "event", "label": "Pressure trip", "summary": "Saved pressure measurements.", "status": "saved", "domain": "rf", "event_id": "RF-TEST", "record_id": "RF-TEST"},
        {"id": DOCUMENT, "kind": "document", "label": "Pressure response procedure", "summary": "Check the original pressure reading.", "status": "unapproved", "record_id": "DOC-1", "version": "Rev 1"},
        {"id": FINDING, "kind": "finding", "label": "Pressure decreased", "summary": "A stored analysis finding.", "status": "measured", "event_id": "RF-TEST", "record_id": "RF-TEST"},
        {"id": DRAFT, "kind": "draft", "label": "Pressure trip review", "summary": "Human review is still needed.", "status": "draft", "event_id": "RF-TEST", "record_id": "DRAFT-TEST"},
        {"id": KNOWLEDGE, "kind": "knowledge", "label": "Motor alignment", "summary": "A separate reviewed mechanical lesson.", "status": "approved", "event_id": "MECH-OLD", "record_id": "KN-MOTOR", "domain": "mechanical"},
        {"id": "topic:pressure", "kind": "topic", "label": "Pressure", "summary": "A shared saved tag.", "status": "shared tag", "record_id": "pressure"},
    ],
    "edges": [
        {"id": "saved-finding", "source": EVENT, "target": FINDING, "kind": "finding", "label": "Stored analysis finding"},
        {"id": "draft-event", "source": DRAFT, "target": EVENT, "kind": "review", "label": "Draft reviews this dataset"},
        {"id": "procedure-source", "source": DRAFT, "target": DOCUMENT, "kind": "source", "label": "Cited in the saved draft"},
        {"id": "event-tag", "source": EVENT, "target": "topic:pressure", "kind": "tag", "label": "Saved tag: pressure"},
        {"id": "document-tag", "source": DOCUMENT, "target": "topic:pressure", "kind": "tag", "label": "Saved tag: pressure"},
    ],
    "counts": {"events": 1, "documents": 1, "drafts": 1, "knowledge": 1, "analyses": 1},
    "shown": {"event": 1, "document": 1, "draft": 1, "knowledge": 1, "finding": 1, "topic": 1},
    "truncated": False,
    "limits": {"records_per_kind": 100, "nodes": 350, "edges": 700},
    "notes": ["Connections describe stored links and shared metadata, not proven causes."],
}


@pytest.fixture
def connections_backend(backend, monkeypatch):
    """Keep real dashboard rendering and replace only the new read endpoint."""
    state = {"graph": copy.deepcopy(GRAPH), "failed": False, "requests": []}
    original_get = requests.get

    def get(url, **kwargs):
        path = urlsplit(url).path
        state["requests"].append(path)
        if path == "/connections":
            if state["failed"]:
                return Response({"detail": "Connection graph temporarily unavailable"}, 503)
            return Response(state["graph"])
        if path == "/knowledge":
            return Response([{
                "knowledge_id": "KN-MOTOR", "event_id": "MECH-OLD",
                "draft": {**copy.deepcopy(backend["draft"]), "summary": "Motor alignment", "status": "approved"},
                "review": {"decision": "approve", "reviewer": "Test engineer", "timestamp": "2026-10-09T12:00:00Z"},
            }])
        return original_get(url, **kwargs)

    monkeypatch.setattr(requests, "get", get)
    return state


def page_text(app):
    return "\n".join(str(item.value) for item in [*app.markdown, *app.caption, *app.info, *app.warning, *app.error])


def assert_read_only(backend, state):
    assert not backend["posts"], "Exploring connections must not ask AI, analyze, save or approve"
    assert not backend["deletes"], "Exploring connections must not delete saved records"
    assert not any(path.startswith(("/rag", "/models", "/events/generate", "/documents/index")) for path in state["requests"])


def test_motion_preference_preserves_selected_idea_and_does_not_write(connections_backend, backend):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(EVENT).run()
    app.checkbox(key="connections_focus").set_value(True).run()
    app.toggle(key="interface_motion").set_value(False).run()
    assert not app.exception
    assert app.session_state["connections_selected_id"] == EVENT
    assert app.checkbox(key="connections_focus").value is True
    assert 'class="frib-motion-off"' in page_text(app)
    app.radio(key="main_nav").set_value("🏠 Home").run()
    assert app.toggle(key="interface_motion").value is False
    app.radio(key="main_nav").set_value(CONNECTIONS).run()
    app.toggle(key="interface_motion").set_value(True).run()
    assert not app.exception
    assert 'class="frib-motion-off"' not in page_text(app)
    assert_read_only(backend, connections_backend)


def test_connections_page_has_keyboard_record_picker_and_explained_connections(connections_backend, backend):
    original = copy.deepcopy(connections_backend["graph"])
    app = open_page(CONNECTIONS)
    assert app.radio(key="main_nav").value == CONNECTIONS
    assert app.selectbox(key="connections_jump")
    assert any(item.label == "Connection list" for item in app.expander)
    relationships = [item.value["Connection"].tolist() for item in app.dataframe if "Connection" in item.value.columns]
    assert any("Cited in the saved draft" in values for values in relationships)
    assert "does not establish a cause" in page_text(app)
    assert connections_backend["requests"].count("/connections") == 1
    assert connections_backend["graph"] == original
    assert_read_only(backend, connections_backend)


def test_connections_search_and_view_filters_only_change_the_visible_graph(connections_backend, backend):
    original = copy.deepcopy(connections_backend["graph"])
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(KNOWLEDGE).run()
    assert app.session_state["connections_selected_id"] == KNOWLEDGE
    app.text_input(key="connections_search").set_value("pressure").run()
    assert not app.exception
    assert not any("Motor alignment" in option for option in app.selectbox(key="connections_jump").options)
    assert app.session_state["connections_selected_id"] != KNOWLEDGE
    app.selectbox(key="connections_view").set_value("Procedures").run()
    assert not app.exception
    assert any("Pressure response procedure" in option for option in app.selectbox(key="connections_jump").options)
    assert not any("Motor alignment" in option for option in app.selectbox(key="connections_jump").options)
    assert connections_backend["graph"] == original
    assert_read_only(backend, connections_backend)


def test_no_matching_connections_do_not_offer_a_stale_record(connections_backend, backend):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(KNOWLEDGE).run()
    app.text_input(key="connections_search").set_value("no-saved-record-matches-7261").run()
    assert not app.exception
    assert app.session_state.get("connections_selected_id") != KNOWLEDGE
    assert not any(item.key == "connections_open_record" and not item.disabled for item in app.button)
    assert any("match" in item.value.casefold() for item in [*app.info, *app.markdown])
    assert_read_only(backend, connections_backend)


@pytest.mark.parametrize("node_id,target", [
    (EVENT, "🔎 Investigate Event"),
    (FINDING, "🔎 Investigate Event"),
    (DOCUMENT, "📁 Files & Documents"),
    (DRAFT, "✅ Review Results"),
    (KNOWLEDGE, "🧠 Engineering Wiki"),
])
def test_native_open_record_goes_to_the_exact_saved_source(connections_backend, backend, node_id, target):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(node_id).run()
    assert not app.exception
    assert app.session_state["connections_selected_id"] == node_id
    assert not app.button(key="connections_open_record").disabled
    app.button(key="connections_open_record").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == target
    if node_id in {EVENT, FINDING}:
        assert app.selectbox(key="investigate_event").value == "RF-TEST"
    elif node_id == DOCUMENT:
        assert app.session_state["document_search"] == "DOC-1"
    elif node_id == DRAFT:
        assert app.selectbox(key="review_event_select").value["event_id"] == "RF-TEST"
    elif node_id == KNOWLEDGE:
        assert app.session_state["selected_knowledge"] == "KN-MOTOR"
        assert any("Motor alignment" in item.label and item.proto.expanded for item in app.expander)
    assert_read_only(backend, connections_backend)


def test_topic_selection_explains_metadata_without_opening_a_fictional_record(connections_backend, backend):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value("topic:pressure").run()
    assert not app.exception
    assert not any(item.key == "connections_open_record" and not item.disabled for item in app.button)
    assert_read_only(backend, connections_backend)


def test_keyboard_neighbor_navigation_and_focus_preserve_the_selected_idea(connections_backend, backend):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(EVENT).run()
    app.checkbox(key="connections_focus").check().run()
    app.button(key="connections_neighbor_0").click().run()
    assert not app.exception
    assert app.session_state["connections_selected_id"] == FINDING
    assert app.selectbox(key="connections_jump").value == FINDING
    assert app.checkbox(key="connections_focus").value is True
    assert any("Pressure decreased" in item.value for item in app.markdown)
    assert_read_only(backend, connections_backend)


def test_empty_workspace_offers_setup_without_a_fabricated_graph(connections_backend, backend):
    connections_backend["graph"] = {**copy.deepcopy(GRAPH), "nodes": [], "edges": [], "counts": {}, "shown": {}}
    app = open_page(CONNECTIONS)
    assert not app.exception
    assert not any(item.key == "connections_jump" for item in app.selectbox)
    assert not any(item.key == "connections_open_record" for item in app.button)
    assert "add" in page_text(app).casefold()
    assert any("data" in item.label.casefold() for item in app.button)
    assert_read_only(backend, connections_backend)


def test_graph_failure_is_visible_retryable_and_never_claims_the_workspace_is_empty(connections_backend, backend):
    connections_backend["failed"] = True
    app = open_page(CONNECTIONS)
    assert any("temporarily unavailable" in item.value for item in app.error)
    assert not any(item.key == "connections_jump" for item in app.selectbox)
    assert not any("no connections" in item.value.casefold() for item in app.info)
    connections_backend["failed"] = False
    app.button(key="connections_retry").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == CONNECTIONS
    assert app.selectbox(key="connections_jump")
    assert not app.error
    assert_read_only(backend, connections_backend)


def test_refresh_clears_a_deleted_record_selection(connections_backend, backend):
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(KNOWLEDGE).run()
    connections_backend["graph"]["nodes"] = [node for node in connections_backend["graph"]["nodes"] if node["id"] != KNOWLEDGE]
    app.button(key="connections_refresh").click().run()
    assert not app.exception
    assert app.session_state.get("connections_selected_id") != KNOWLEDGE
    assert not any("Motor alignment" in option for option in app.selectbox(key="connections_jump").options)
    assert not any(item.key == "connections_open_record" and not item.disabled for item in app.button)
    assert_read_only(backend, connections_backend)


def test_malformed_graph_shows_a_recoverable_error(connections_backend, backend):
    connections_backend["graph"]["nodes"] = "not a node list"
    app = open_page(CONNECTIONS)
    assert not app.exception
    assert app.error
    assert app.button(key="connections_retry")
    assert not any(item.key == "connections_open_record" for item in app.button)
    assert_read_only(backend, connections_backend)


def test_user_controlled_headings_are_escaped_and_summary_stays_plain_text(connections_backend, backend):
    label = '</h3><img src=x onerror="alert(1)"><script>bad()</script>'
    summary = "![Remote image](https://example.invalid/user-data) <script>bad()</script>"
    connections_backend["graph"]["nodes"][0].update(label=label, summary=summary)
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(EVENT).run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "&lt;img" in markup and "&lt;script&gt;" in markup
    assert '<img src=x onerror=' not in markup
    assert any(item.value == summary for item in app.text)
    assert_read_only(backend, connections_backend)


def test_saved_labels_and_connection_reasons_cannot_load_markdown_images(connections_backend, backend):
    remote_image = "![remote pixel](https://example.invalid/private-record)"
    connections_backend["graph"]["nodes"][1].update(label=remote_image, version=remote_image)
    connections_backend["graph"]["edges"][2]["label"] = remote_image
    connections_backend["graph"]["notes"] = [remote_image]
    app = open_page(CONNECTIONS)
    app.selectbox(key="connections_jump").set_value(DRAFT).run()
    assert not app.exception
    neighbor_labels = [item.label for item in app.button if str(item.key).startswith("connections_neighbor_")]
    assert any("remote pixel" in label for label in neighbor_labels)
    assert not any(re.search(r"(?<!\\)!\[", label) for label in neighbor_labels)
    assert not any(re.search(r"(?<!\\)!\[", item.value) for item in app.caption)
    app.selectbox(key="connections_jump").set_value(DOCUMENT).run()
    assert not app.exception
    assert not any(re.search(r"(?<!\\)!\[", item.value) for item in app.caption)
    assert_read_only(backend, connections_backend)


def test_connections_footer_resumes_the_investigation_step(connections_backend, backend):
    app = open_page("🔎 Investigate Event")
    app.button(key="workflow_next").click().run()
    assert app.session_state["investigation_tabs"] == "2 · What changed"
    app.radio(key="main_nav").set_value(CONNECTIONS).run()
    assert not app.exception
    app.button(key="workflow_next").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "🔎 Investigate Event"
    assert app.session_state["investigation_tabs"] == "2 · What changed"
    assert_read_only(backend, connections_backend)
