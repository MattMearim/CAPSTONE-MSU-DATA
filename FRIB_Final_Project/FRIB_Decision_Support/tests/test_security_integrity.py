"""Adversarial regressions for evidence, review and retrieval integrity.

All records, databases and lock files live in pytest's disposable directories.
No running application's data is modified by these tests.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Barrier

import pytest

from frib_ds.knowledge.service import KnowledgeService
from frib_ds.models import (
    AnalysisResult, DocumentChunk, EngineeringEvent, KnowledgeDraft,
    ReviewRequest,
)
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.llm import MockLLMProvider
from frib_ds.rag.service import RAGService
from frib_ds.storage.reset import DataLifecycleLock
from frib_ds.storage.sqlite import SQLiteRepository


PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class DraftModel:
    def chat(self, *_args, **_kwargs):
        return json.dumps({
            "draft_id": "ATTACKER-ID", "event_id": "ATTACKER-EVENT",
            "summary": "Requires review", "status": "approved",
            "generated_by": "human", "created_at": "9999-12-31T23:59:59Z",
            "observations": ["Invented measurement"],
            "relevant_sources": ["Invented approved source"],
            "evidence_snapshot": {"event_sha256": "forged"},
        })


def event_and_analysis():
    event = EngineeringEvent(event_id="SECURITY-E1", domain="rf", event_type="test",
                             provenance={"source": "test"})
    analysis = AnalysisResult(event_id=event.event_id, processor="test",
                              processor_version="1", findings=["Measured evidence"])
    return event, analysis


def test_model_cannot_control_draft_identity_time_status_or_measured_evidence(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite")
    event, analysis = event_and_analysis()
    before = datetime.now(timezone.utc)
    draft = KnowledgeService(repo, DraftModel(), PROMPTS).create_draft(event, analysis)
    after = datetime.now(timezone.utc)

    assert before <= draft.created_at <= after
    assert draft.draft_id.startswith("DRAFT-") and draft.event_id == event.event_id
    assert draft.status == "draft" and draft.generated_by != "human"
    assert draft.observations == analysis.findings and draft.relevant_sources == []
    assert draft.evidence_snapshot["event_sha256"] != "forged"
    assert repo.list_knowledge() == []


def chunk():
    return DocumentChunk(chunk_id="C1", document_id="DOC-1234567890", title="RF procedure",
                         text="Review recorded pressure evidence.", approved=True)


def metadata():
    return {"document_id": "DOC-1234567890", "filename": "procedure.md",
            "title": "RF procedure", "version": "1", "approved": True,
            "uploaded_at": datetime.now(timezone.utc).isoformat(), "checksum": "abc",
            "size_bytes": 30, "indexed_chunks": 1}


@pytest.mark.parametrize("vectors", [[], [[float("nan")]], [[float("inf")]], [[]], [[True]], [[10**1000]]])
def test_invalid_embedding_output_cannot_silently_commit_a_partial_catalog(tmp_path, vectors):
    repo = SQLiteRepository(tmp_path / "app.sqlite")
    with pytest.raises(ValueError):
        repo.save_document(metadata(), [chunk()], vectors)
    assert repo.list_documents() == []
    assert repo.approved_document_chunks() == []


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_similarity_is_not_evidence_of_relevance(score):
    class InvalidScoreStore:
        def search(self, *_args):
            return [(chunk(), score)]

    service = RAGService(HashEmbeddingProvider(32), InvalidScoreStore(), MockLLMProvider(),
                         {"retrieval": {"minimum_score": 0.2}}, PROMPTS)
    response = service.query("RF pressure evidence")
    assert not response.sources and not response.grounded


def test_simultaneous_conflicting_human_reviews_publish_exactly_once(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite")
    original = KnowledgeDraft(draft_id="D1", event_id="E1", summary="Original evidence")
    repo.save_draft(original)
    barrier = Barrier(2)

    def review(decision):
        barrier.wait(timeout=5)
        try:
            KnowledgeService(repo, MockLLMProvider(), PROMPTS).review(
                original, ReviewRequest(decision=decision, reviewer=decision + " reviewer"))
            return decision
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, ["approve", "escalate"]))
    accepted = [decision for decision in results if decision]
    assert len(accepted) == 1
    assert len(repo.list_audit()) == 1
    assert len(repo.list_knowledge()) == (1 if accepted[0] == "approve" else 0)
    assert repo.get_draft("D1").status == ("approved" if accepted[0] == "approve" else "escalated")


def test_sql_injection_text_is_stored_and_searched_as_data(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite")
    payload = "'; DROP TABLE drafts; --"
    draft = KnowledgeDraft(draft_id="D1", event_id="E1", summary=payload)
    repo.save_draft(draft)
    KnowledgeService(repo, MockLLMProvider(), PROMPTS).review(
        draft, ReviewRequest(decision="approve", reviewer=payload))

    found = repo.search_knowledge(payload)
    assert len(found) == 1 and found[0].draft.summary == payload
    assert repo.get_draft("D1").status == "approved"
    assert repo.search_knowledge("' OR 1=1 --") == []


def test_lifecycle_lock_excludes_a_second_worker_and_releases_on_error(tmp_path):
    with pytest.raises(RuntimeError):
        with DataLifecycleLock(tmp_path):
            other = DataLifecycleLock(tmp_path)
            try:
                assert not other.try_acquire()
            finally:
                other.close()
            raise RuntimeError("Simulated request failure")
    with DataLifecycleLock(tmp_path) as next_worker:
        assert next_worker.locked


@pytest.mark.parametrize("provider", ["memory", "sqlite"])
def test_second_worker_refreshes_document_additions_and_deletions(tmp_path, monkeypatch, provider):
    from frib_ds.bootstrap import Services, get_services
    from frib_ds.config import get_config

    monkeypatch.setenv("FRIB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRIB_CONFIG_DIR", str(PROMPTS.parent / "config"))
    monkeypatch.setenv("FRIB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("FRIB_VECTOR_PROVIDER", provider)
    get_config.cache_clear()
    get_services.cache_clear()
    try:
        first = Services()
        uploaded = first.documents.upload("procedure.md", b"RF cavity pressure review procedure.", approved=True)
        second = Services()
        assert second.rag.query("RF cavity pressure review procedure").sources
        first.documents.delete(uploaded["document_id"])
        assert second.refresh_data_state()
        assert second.rag.query("RF cavity pressure review procedure").sources == []
        replacement = first.documents.upload("replacement.md", b"RF cavity pressure review procedure updated.", approved=True)
        assert second.refresh_data_state()
        retrieved = second.rag.query("RF cavity pressure review procedure").sources
        assert retrieved and {source.document_id for source in retrieved} == {replacement["document_id"]}
    finally:
        get_config.cache_clear()
        get_services.cache_clear()
