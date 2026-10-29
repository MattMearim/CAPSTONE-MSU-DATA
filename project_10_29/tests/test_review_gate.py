from pathlib import Path
from tempfile import TemporaryDirectory
from frib_ds.storage.sqlite import SQLiteRepository
from frib_ds.knowledge.service import KnowledgeService
from frib_ds.rag.llm import MockLLMProvider
from frib_ds.models import KnowledgeDraft, ReviewRequest, ReviewDecision
import pytest

def test_escalate_does_not_publish():
    with TemporaryDirectory() as td:
        repo=SQLiteRepository(Path(td)/"x.db"); svc=KnowledgeService(repo,MockLLMProvider(),"prompts")
        d=KnowledgeDraft(draft_id="D1",event_id="E1",summary="x"); repo.save_draft(d)
        review,k=svc.review(d,ReviewRequest(decision=ReviewDecision.escalate,reviewer="tester"))
        assert k is None and repo.list_knowledge()==[]

def test_approve_publishes():
    with TemporaryDirectory() as td:
        repo=SQLiteRepository(Path(td)/"x.db"); svc=KnowledgeService(repo,MockLLMProvider(),"prompts")
        d=KnowledgeDraft(draft_id="D1",event_id="E1",summary="x"); repo.save_draft(d)
        review,k=svc.review(d,ReviewRequest(decision=ReviewDecision.approve,reviewer="tester"))
        assert k is not None and len(repo.list_knowledge())==1


def test_repeated_or_stale_approval_cannot_publish_twice(tmp_path):
    repo=SQLiteRepository(tmp_path/"x.db")
    svc=KnowledgeService(repo,MockLLMProvider(),"prompts")
    original=KnowledgeDraft(draft_id="D1",event_id="E1",summary="Original")
    repo.save_draft(original)
    svc.review(original, ReviewRequest(decision="approve", reviewer="Engineer"))
    with pytest.raises(ValueError, match="already"):
        svc.review(original, ReviewRequest(decision="escalate", reviewer="Engineer"))
    assert len(repo.list_knowledge()) == 1
    assert repo.get_draft("D1").status == "approved"


def test_correction_keeps_evidence_and_audits_original(tmp_path):
    repo=SQLiteRepository(tmp_path/"x.db")
    svc=KnowledgeService(repo,MockLLMProvider(),"prompts")
    original=KnowledgeDraft(draft_id="D1",event_id="E1",summary="Original", evidence_snapshot={"event_sha256":"original-hash"})
    repo.save_draft(original)
    corrected=original.model_copy(update={"summary":"Corrected summary", "event_id":"WRONG", "evidence_snapshot":{}})
    _, knowledge=svc.review(original, ReviewRequest(decision="correct",reviewer="Engineer",corrected_draft=corrected))
    assert knowledge.draft.event_id == "E1"
    assert knowledge.draft.evidence_snapshot["event_sha256"] == "original-hash"
    assert "Original" in str(repo.list_audit())


def test_draft_hash_uses_actual_legacy_original_bytes(tmp_path):
    import hashlib
    from frib_ds.models import EngineeringEvent, AnalysisResult
    from frib_ds.storage.files import EventFileStore
    event=EngineeringEvent(event_id="LEGACY1", domain="rf", event_type="test", provenance={"source":"import"})
    files=EventFileStore(tmp_path/"events")
    path=files.save(event)
    # Simulate a capture written by the previous Windows text writer.
    original=event.model_dump_json(indent=2).replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(original)
    repo=SQLiteRepository(tmp_path/"x.db")
    svc=KnowledgeService(repo,MockLLMProvider(),Path(__file__).resolve().parents[1]/"prompts",files)
    draft=svc.create_draft(event,AnalysisResult(event_id=event.event_id,processor="test",processor_version="1"))
    assert draft.evidence_snapshot["event_sha256"]==hashlib.sha256(original).hexdigest()
    assert draft.evidence_snapshot["event_sha256_scope"]=="stored_original_event_json"
