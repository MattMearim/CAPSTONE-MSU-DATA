from pathlib import Path
import pytest
from frib_ds.models import DocumentChunk, EngineeringEvent
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.llm import MockLLMProvider
from frib_ds.rag.service import RAGService
from frib_ds.rag.vector_store import MemoryVectorStore


class Model:
    def __init__(self, answer=None):
        self.answer = answer
    def chat(self, *args, **kwargs):
        if self.answer is None:
            raise RuntimeError("Model is offline")
        return self.answer


def service(llm, approved=True, title="RF procedure"):
    embedding, store = HashEmbeddingProvider(128), MemoryVectorStore()
    chunk = DocumentChunk(chunk_id="C1", document_id="D1", title=title, text="Review cavity pressure evidence before assigning a cause.", approved=approved, version="2")
    store.add([chunk], embedding.embed([chunk.text]))
    return RAGService(embedding, store, llm, {"retrieval": {"minimum_score": -1}}, Path(__file__).resolve().parents[1] / "prompts")


def test_demo_returns_real_excerpts_with_versions():
    result = service(MockLLMProvider()).query("cavity pressure")
    assert result.mode == "extractive" and result.grounded
    assert result.sources[0].version == "2" and "Review cavity pressure" in result.answer
    assert result.interpretation is None


@pytest.mark.parametrize("answer", [None, "Unsupported answer", "Claim [S99]"])
def test_offline_or_uncited_model_answer_is_not_grounded(answer):
    result = service(Model(answer)).query("cavity pressure")
    assert result.mode == "unavailable" and not result.grounded and result.error
    assert result.sources and result.interpretation is None


def test_cited_model_answer_retains_citations():
    result = service(Model("Review the evidence [S1].")).query("cavity pressure")
    assert result.mode == "llm" and result.grounded and result.interpretation


def test_unapproved_sources_never_retrieved():
    result = service(MockLLMProvider(), approved=False).query("cavity pressure")
    assert not result.grounded and not result.sources


def test_explicit_wrong_domain_does_not_fallback():
    event = EngineeringEvent(event_id="E1", domain="rf", event_type="trip", provenance={"source": "test"})
    result = service(MockLLMProvider(), title="PLC procedure").query("cavity pressure", event)
    assert not result.sources and not result.grounded


def test_rf_interlock_document_is_not_misclassified_as_plc():
    event = EngineeringEvent(event_id="E1", domain="rf", event_type="trip", provenance={"source": "test"})
    result = service(MockLLMProvider(), title="RF interlock procedure").query("cavity pressure", event)
    assert result.sources and result.grounded
