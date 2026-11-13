"""Saved relationship extraction stays bounded, truthful, and read only."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from frib_ds.api import main as api
from frib_ds.connections import MAX_NODES, MAX_EDGES, MAX_PAYLOAD_BYTES, build_connections, read_connection_snapshot, workspace_connections
from frib_ds.models import AnalysisResult, DocumentChunk, EngineeringEvent, KnowledgeDraft, KnowledgeRecord, Provenance, ReviewRecord
from frib_ds.storage.sqlite import SQLiteRepository


@pytest.fixture
def repository(tmp_path):
    return SQLiteRepository(tmp_path / "catalog.sqlite3")


def add_event(repository, event_id="EVENT-1", domain="rf"):
    event = EngineeringEvent(event_id=event_id, domain=domain, event_type="Pressure excursion", metadata={"dataset_name": "Training pressure capture", "secret": "PRIVATE-METADATA"},
                             provenance=Provenance(source="uploaded", notes="PRIVATE-PROVENANCE"))
    repository.save_event(event)
    repository.save_analysis(AnalysisResult(event_id=event_id, processor="rf", processor_version="1", findings=["Pressure rose before the trip."], features={"private": "PRIVATE-FEATURES"}))
    return event


def add_document(repository, document_id="DOC-1", approved=True):
    chunk_id = f"{document_id}-chunk"
    chunk = DocumentChunk(chunk_id=chunk_id, document_id=document_id, title="Pressure response procedure", text="PRIVATE-DOCUMENT-BODY", approved=approved, source_path="/Users/private/document.md")
    repository.save_document({"document_id": document_id, "filename": "private-procedure.md", "title": chunk.title, "version": "2.1", "approved": approved,
                              "uploaded_at": "2026-11-01T12:00:00+00:00", "checksum": "private-checksum", "size_bytes": 32, "indexed_chunks": 1 if approved else 0,
                              "approval_metadata": {"reviewer": "PRIVATE-REVIEWER"}}, [chunk] if approved else [], [[0.1, 0.9]] if approved else [])
    return chunk_id


def add_draft(repository, draft_id="DRAFT-1", event_id="EVENT-1", status="draft", sources=None):
    draft = KnowledgeDraft(draft_id=draft_id, event_id=event_id, summary="Saved pressure investigation", status=status, tags=["pressure", "rf"],
                           relevant_sources=["Invented free-text document=DOC-do-not-link"],
                           evidence_snapshot={"retrieval": {"answer": "PRIVATE-ANSWER", "sources": sources or []}})
    repository.save_draft(draft)
    return draft


def source(document_id="DOC-1", chunk_id="DOC-1-chunk"):
    return {"document_id": document_id, "chunk_id": chunk_id, "title": "reference", "label": "S1", "excerpt": "PRIVATE-SOURCE-EXCERPT", "page": 2}


def add_knowledge(repository, draft):
    review = ReviewRecord(review_id="REVIEW-1", draft_id=draft.draft_id, event_id=draft.event_id, decision="approve", reviewer="PRIVATE-REVIEWER", comments="PRIVATE-COMMENTS")
    knowledge = KnowledgeRecord(knowledge_id="KNOW-1", event_id=draft.event_id, draft=draft, review=review, searchable_text="PRIVATE-SEARCH-TEXT")
    repository.save_knowledge(knowledge)
    return knowledge


def test_empty_workspace_has_no_fabricated_nodes(repository):
    graph = workspace_connections(repository)
    assert graph["nodes"] == graph["edges"] == []
    assert graph["counts"] == dict.fromkeys(["events", "documents", "drafts", "knowledge", "analyses"], 0)
    assert graph["truncated"] is False


def test_graph_uses_explicit_relationships_and_preserves_review_state(repository):
    add_event(repository)
    add_document(repository)
    add_document(repository, "DOC-unapproved", approved=False)
    add_draft(repository, sources=[source()])
    approved = add_draft(repository, "DRAFT-reviewed", status="approved", sources=[source()])
    add_knowledge(repository, approved)
    graph = workspace_connections(repository)
    nodes = {node["record_id"]: node for node in graph["nodes"]}
    assert nodes["DRAFT-1"]["status"] == "draft"
    assert nodes["KNOW-1"]["status"] == "approved"
    assert nodes["DOC-1"]["status"] == "approved"
    assert nodes["DOC-unapproved"]["status"] == "unapproved"
    assert nodes["EVENT-1"]["label"] == "Training pressure capture"
    assert nodes["DRAFT-1"]["event_id"] == "EVENT-1"
    assert {edge["kind"] for edge in graph["edges"]} == {"in_domain", "has_finding", "has_draft", "has_knowledge", "reviewed_as", "cites", "tagged_with"}
    citations = [edge for edge in graph["edges"] if edge["kind"] == "cites"]
    assert len(citations) == 3
    assert all(edge["target"] == nodes["DOC-1"]["id"] for edge in citations)
    node_ids = {node["id"] for node in graph["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"])


def test_map_does_not_expose_evidence_bodies_vectors_or_reviewer_identity(repository):
    add_event(repository)
    add_document(repository)
    draft = add_draft(repository, status="approved", sources=[source()])
    add_knowledge(repository, draft)
    before = repository.path.read_bytes()
    graph = workspace_connections(repository)
    serialized = json.dumps(graph)
    assert "PRIVATE-" not in serialized
    assert "/Users/" not in serialized and "private-checksum" not in serialized
    assert "searchable_text" not in serialized and "source_path" not in serialized
    assert repository.path.read_bytes() == before
    assert workspace_connections(repository) == graph


@pytest.mark.parametrize("bad_source", [source("DOC-missing"), source(chunk_id="invented-chunk"), source("DOC-other", "DOC-1-chunk"), {"document_id": ["DOC-1"], "chunk_id": "DOC-1-chunk"}])
def test_invalid_or_deleted_citation_cannot_create_a_link(repository, bad_source):
    add_event(repository)
    add_document(repository)
    add_document(repository, "DOC-other")
    add_draft(repository, sources=[bad_source])
    graph = workspace_connections(repository)
    assert not [edge for edge in graph["edges"] if edge["kind"] == "cites"]
    assert graph["missing_reference_count"] == 1
    assert graph["truncated"] is True
    repository.delete_document("DOC-1")
    assert not [node for node in workspace_connections(repository)["nodes"] if node["record_id"] == "DOC-1"]


def test_free_text_source_claims_and_matching_words_never_create_links(repository):
    add_event(repository)
    add_document(repository)
    add_draft(repository)
    graph = workspace_connections(repository)
    assert not [edge for edge in graph["edges"] if edge["kind"] == "cites"]
    assert not any(edge["kind"] in {"similar", "causes", "supports"} for edge in graph["edges"])


def test_knowledge_requires_consistent_explicit_human_review(repository):
    add_event(repository)
    draft = add_draft(repository, status="draft")
    knowledge = add_knowledge(repository, draft)
    graph = workspace_connections(repository)
    assert next(node for node in graph["nodes"] if node["kind"] == "knowledge")["status"] == "unverified"
    assert not any(edge["kind"] == "reviewed_as" for edge in graph["edges"])
    knowledge.draft.status = "corrected"  # An approve decision is not a correction.
    repository.save_knowledge(knowledge)
    graph = workspace_connections(repository)
    assert next(node for node in graph["nodes"] if node["kind"] == "knowledge")["status"] == "unverified"


def test_malformed_nested_history_cannot_crash_the_map_or_claim_approval(repository):
    add_event(repository)
    draft = add_draft(repository, status="approved")
    add_knowledge(repository, draft)
    with repository.connect() as connection:
        payload = json.loads(connection.execute("SELECT payload FROM knowledge").fetchone()[0])
        payload["review"]["decision"] = ["approve"]
        payload["draft"]["draft_id"] = {"unsafe": "DRAFT-1"}
        payload["draft"]["tags"] = [None, {"unsafe": "pressure"}, "pressure\x00tag"]
        connection.execute("UPDATE knowledge SET payload=?", (json.dumps(payload),))
    graph = workspace_connections(repository)
    assert next(node for node in graph["nodes"] if node["kind"] == "knowledge")["status"] == "unverified"
    assert not any(edge["kind"] == "reviewed_as" for edge in graph["edges"])
    assert all("\x00" not in node["label"] for node in graph["nodes"])


def test_large_and_malformed_history_remains_bounded_and_truthfully_marked(repository):
    add_event(repository)
    add_draft(repository)
    with repository.connect() as connection:
        connection.execute("UPDATE drafts SET payload=?", ("x" * (MAX_PAYLOAD_BYTES + 1),))
        connection.execute("UPDATE analyses SET payload='broken-json'")
    graph = workspace_connections(repository)
    assert graph["omitted_detail_count"] == 2
    assert graph["truncated"]
    assert next(node for node in graph["nodes"] if node["kind"] == "draft")["label"] == "Knowledge draft"
    assert len(json.dumps(graph)) < 20_000


def test_record_limit_keeps_real_older_parent_of_selected_draft(repository):
    add_event(repository, "EVENT-old")
    add_event(repository, "EVENT-new")
    add_document(repository, "DOC-old")
    add_draft(repository, event_id="EVENT-old", sources=[source("DOC-old", "DOC-old-chunk")])
    graph = workspace_connections(repository, limit=1)
    assert any(node["record_id"] == "EVENT-old" for node in graph["nodes"])
    assert any(edge["kind"] == "has_draft" for edge in graph["edges"])
    assert any(edge["kind"] == "cites" for edge in graph["edges"])
    assert graph["truncated"]


def test_graph_budget_preserves_core_records_and_never_returns_dangling_edges():
    snapshot = {"events": [], "documents": [], "drafts": [], "knowledge": [], "analyses": [], "chunk_pairs": set(), "counts": {}, "limit": 100}
    for i in range(100):
        event_id = f"EVENT-{i}"
        snapshot["events"].append({"event_id": event_id, "domain": "rf", "event_type": "trip"})
        snapshot["documents"].append({"document_id": f"DOC-{i}", "title": "Procedure", "approved": False})
        snapshot["drafts"].append({"draft_id": f"DRAFT-{i}", "event_id": event_id, "status": "draft", "payload": {"summary": "Draft", "tags": [f"tag-{i}-{j}" for j in range(100)]}})
        snapshot["analyses"].append({"event_id": event_id, "payload": {"findings": ["observation"] * 100}})
    graph = build_connections(snapshot)
    assert len(graph["nodes"]) <= MAX_NODES and len(graph["edges"]) <= MAX_EDGES
    assert graph["shown"]["event"] == graph["shown"]["document"] == graph["shown"]["draft"] == 100
    assert graph["truncated"]
    node_ids = {node["id"] for node in graph["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"])


@pytest.mark.parametrize("limit", [0, 101, -1, True, "60"])
def test_repository_boundary_rejects_invalid_limit(repository, limit):
    with pytest.raises(ValueError, match="limit"):
        read_connection_snapshot(repository, limit)


def test_connections_endpoint_is_bounded_local_read_only_and_reset_guarded(repository, tmp_path, monkeypatch):
    add_event(repository)
    state = {"ready": True}
    services = SimpleNamespace(repo=repository, refresh_data_state=lambda: state["ready"])
    monkeypatch.setattr(api, "get_services", lambda: services)
    monkeypatch.setattr(api, "get_config", lambda: SimpleNamespace(data_dir=tmp_path))
    before = repository.path.read_bytes()
    with TestClient(api.app) as client:
        response = client.get("/connections")
        assert response.status_code == 200, response.text
        assert response.json()["counts"]["events"] == 1
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/connections?limit=101").status_code == 422
        assert client.get("/connections?limit=0").status_code == 422
        assert client.get("/connections", headers={"Origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/connections", json={}).status_code == 405
        state["ready"] = False
        assert client.get("/connections").status_code == 503
    assert repository.path.read_bytes() == before
