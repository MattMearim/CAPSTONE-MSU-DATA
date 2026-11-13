"""The approachable home page opens real records and safely renders their titles."""
from __future__ import annotations

import copy
from html import escape
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from test_dashboard_ui import Response, backend
from test_workbench_ui import (
    assert_workspace_mode_rendered,
    overview,
    workbench_backend,
)


@pytest.fixture
def wiki_home_backend(backend, workbench_backend, monkeypatch):
    """Use distinct identities and overlapping names to expose incorrect routing."""
    workbench_backend["events"][1]["metadata"]["dataset_name"] = "Bearing survey"
    first_document = backend["documents"][0]
    first_document["title"] = "RF startup procedure"
    bearing_document = copy.deepcopy(first_document)
    bearing_document.update(
        document_id="DOC-BEARING", filename="bearing_procedure.md",
        title="Bearing inspection procedure", approved=True,
    )
    backend["documents"].append(bearing_document)

    records = []
    for identifier, event_id, summary in [
        ("KNOW-RF", "RF-TEST", "Reviewed RF field trip"),
        ("KNOW-BEARING", "MECH-SECOND", "Reviewed bearing inspection"),
    ]:
        draft = copy.deepcopy(backend["draft"])
        draft.update(event_id=event_id, summary=summary, status="approved")
        records.append({
            "knowledge_id": identifier, "event_id": event_id, "draft": draft,
            "review": {"decision": "approve", "reviewer": "Jane Smith",
                       "timestamp": "2026-10-09T12:00:00Z", "comments": "Evidence checked"},
            "searchable_text": summary, "created_at": "2026-10-09T12:00:00Z",
        })

    original_get = requests.get

    def get(url, **kwargs):
        location = urlsplit(url)
        if location.path == "/knowledge":
            return Response(records)
        if location.path == "/knowledge/search":
            query = parse_qs(location.query).get("q", [""])[0].casefold()
            return Response([
                row for row in records if query in " ".join([
                    row["knowledge_id"], row["event_id"], row["searchable_text"],
                ]).casefold()
            ])
        return original_get(url, **kwargs)

    monkeypatch.setattr(requests, "get", get)
    return {"events": workbench_backend["events"], "documents": backend["documents"],
            "knowledge": records, "writes": backend}


@pytest.mark.parametrize("key,target", [
    ("home_add_data", "🧪 Create Dataset"),
    ("home_explore", "🔎 Investigate Event"),
    ("home_ask", "💬 Ask Assistant"),
])
def test_task_cards_open_the_promised_workspace_without_writing(wiki_home_backend, key, target):
    app = overview()
    app.button(key=key).click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == target
    if key == "home_add_data":
        assert_workspace_mode_rendered(app, "Import data")
    assert wiki_home_backend["writes"]["posts"] == []
    assert wiki_home_backend["writes"]["deletes"] == []


def search_result_keys(app):
    return {button.key for button in app.button
            if button.key and button.key.startswith("home_search_")}


def test_workspace_search_filters_all_three_collections_case_insensitively(wiki_home_backend):
    app = overview()
    app.text_input(key="home_search").set_value("  BeArInG  ").run()
    assert not app.exception
    assert search_result_keys(app) == {
        "home_search_event_MECH-SECOND", "home_search_doc_DOC-BEARING",
        "home_search_knowledge_KNOW-BEARING",
    }
    assert wiki_home_backend["writes"]["posts"] == []


@pytest.mark.parametrize("query,key", [
    ("MECH-SECOND", "home_search_event_MECH-SECOND"),
    ("DOC-BEARING", "home_search_doc_DOC-BEARING"),
    ("KNOW-BEARING", "home_search_knowledge_KNOW-BEARING"),
])
def test_workspace_search_accepts_source_record_identifiers(wiki_home_backend, query, key):
    app = overview()
    app.text_input(key="home_search").set_value(query).run()
    assert not app.exception
    assert key in search_result_keys(app)


def test_search_result_opens_the_matched_dataset_instead_of_first_record(wiki_home_backend):
    app = overview()
    app.text_input(key="home_search").set_value("bearing").run()
    app.button(key="home_search_event_MECH-SECOND").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "🔎 Investigate Event"
    assert app.selectbox(key="investigate_event").value == "MECH-SECOND"
    assert wiki_home_backend["writes"]["posts"] == []


def test_search_result_opens_the_matched_document_instead_of_first_record(wiki_home_backend):
    app = overview()
    app.text_input(key="home_search").set_value("bearing").run()
    app.button(key="home_search_doc_DOC-BEARING").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "📁 Files & Documents"
    assert app.selectbox(key="selected_document").value["document_id"] == "DOC-BEARING"
    assert wiki_home_backend["writes"]["posts"] == []


def test_search_result_opens_only_the_matched_reviewed_knowledge(wiki_home_backend):
    app = overview()
    app.text_input(key="home_search").set_value("bearing").run()
    app.button(key="home_search_knowledge_KNOW-BEARING").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == "🧠 Engineering Wiki"
    assert app.session_state["selected_knowledge"] == "KNOW-BEARING"
    records = [item for item in app.expander
               if "Reviewed RF field trip" in item.label
               or "Reviewed bearing inspection" in item.label]
    assert len(records) == 2
    expanded = [item for item in records if item.proto.expanded]
    assert len(expanded) == 1
    assert "MECH-SECOND · Reviewed bearing inspection" in expanded[0].label
    assert wiki_home_backend["writes"]["posts"] == []


def test_no_search_matches_cannot_open_stale_record(wiki_home_backend):
    app = overview()
    app.text_input(key="home_search").set_value("bearing").run()
    assert search_result_keys(app)
    app.text_input(key="home_search").set_value("no-such-record-92851").run()
    assert not app.exception
    assert search_result_keys(app) == set()
    assert any("no" in item.value.casefold()
               and any(word in item.value.casefold() for word in ("match", "found", "result"))
               for item in [*app.info, *app.markdown, *app.caption])
    assert wiki_home_backend["writes"]["posts"] == []


def test_html_titles_are_visible_literal_text_in_home_search_cards(wiki_home_backend):
    malicious_titles = [
        '<img src=x onerror="alert(1)"> dataset',
        '<script>alert("document")</script> procedure',
        '<svg onload="alert(2)"> reviewed record',
    ]
    wiki_home_backend["events"][1]["metadata"]["dataset_name"] = malicious_titles[0]
    wiki_home_backend["documents"][1]["title"] = malicious_titles[1]
    wiki_home_backend["knowledge"][1]["draft"]["summary"] = malicious_titles[2]
    app = overview()
    app.text_input(key="home_search").set_value("alert").run()
    assert not app.exception
    assert search_result_keys(app) == {
        "home_search_event_MECH-SECOND", "home_search_doc_DOC-BEARING",
        "home_search_knowledge_KNOW-BEARING",
    }
    html = "\n".join(item.value for item in app.markdown if item.proto.allow_html)
    for title in malicious_titles:
        assert title not in html
        assert escape(title) in html
