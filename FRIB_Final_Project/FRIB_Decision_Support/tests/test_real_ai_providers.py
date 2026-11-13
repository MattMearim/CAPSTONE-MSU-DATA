"""Provider defaults and failure boundaries without downloading model weights."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from frib_ds.config import Config
from frib_ds.knowledge.service import KnowledgeGenerationUnavailable, KnowledgeService
from frib_ds.models import AnalysisResult, EngineeringEvent
from frib_ds.rag import embeddings, llm
from frib_ds.storage.sqlite import SQLiteRepository


PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("missing_models,expected_model", [(False,"qwen3:4b"),(True,"qwen3:8b")])
def test_runtime_and_missing_configuration_default_to_real_models(tmp_path, monkeypatch, missing_models,expected_model):
    for name in ("FRIB_LLM_PROVIDER", "FRIB_LLM_MODEL", "FRIB_EMBEDDING_PROVIDER", "FRIB_EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FRIB_DATA_DIR", str(tmp_path / "data"))
    configuration = tmp_path / "config" if missing_models else PROJECT / "config"
    configuration.mkdir(exist_ok=True)

    configured = Config(configuration)

    assert configured.models["llm"]["provider"] == "ollama"
    assert configured.models["llm"]["model"] == expected_model
    assert configured.models["embeddings"]["provider"] == "sentence_transformers"
    assert configured.models["embeddings"]["model"] == "all-MiniLM-L6-v2"


def test_factory_defaults_use_real_providers(monkeypatch):
    created = []
    monkeypatch.setattr(embeddings, "SentenceTransformerEmbeddingProvider", lambda **options: created.append(options))

    model = llm.build_llm_provider({})
    embeddings.build_embedding_provider({})

    assert isinstance(model, llm.OllamaProvider)
    assert model.model == "qwen3:8b"
    assert created == [{"model_name": "all-MiniLM-L6-v2", "device": "cpu", "cache_folder": None}]


def test_ollama_allows_automatic_gpu_selection(monkeypatch):
    calls = []

    def post(url, **options):
        calls.append((url, options))
        return SimpleNamespace(ok=True, json=lambda: {"message": {"content": "Cited answer [S1]."}})

    monkeypatch.setattr(llm.requests, "post", post)
    result = llm.build_llm_provider({}).chat([{"role": "user", "content": "Question"}])

    assert result == "Cited answer [S1]."
    assert "num_gpu" not in calls[0][1]["json"]["options"]
    assert calls[0][1]["json"]["stream"] is False


def test_semantic_model_uses_configured_cache_and_normalized_encoding(tmp_path, monkeypatch):
    calls = []

    class SemanticModel:
        def __init__(self, name, **options):
            calls.append((name, options))

        def encode(self, texts, **options):
            calls.append((texts, options))
            return np.asarray([[0.6, 0.8]])

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=SemanticModel))
    monkeypatch.setenv("FRIB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("FRIB_EMBEDDING_CACHE", str(tmp_path / "models"))
    configuration = Config(PROJECT / "config")

    provider = embeddings.build_embedding_provider(configuration.models["embeddings"])
    vectors = provider.embed(["Evidence"])

    assert vectors == [[0.6, 0.8]]
    assert calls[0] == ("all-MiniLM-L6-v2", {"device": "cpu", "cache_folder": str(tmp_path / "models")})
    assert calls[1][1]["normalize_embeddings"] is True


def test_semantic_model_load_failure_never_substitutes_hash(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("Model download unavailable")

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=fail))
    with pytest.raises(RuntimeError, match="Hash embeddings were not substituted") as failure:
        embeddings.build_embedding_provider({})
    assert isinstance(failure.value.__cause__, OSError)


def test_missing_semantic_dependencies_request_repair_without_hash_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(RuntimeError, match="repair the application environment") as failure:
        embeddings.build_embedding_provider({})
    assert isinstance(failure.value.__cause__, ImportError)


@pytest.mark.parametrize("response", [None, "not json", "{}"])
def test_failed_real_generation_creates_no_deterministic_draft(tmp_path, response):
    class FailedModel:
        def chat(self, *_args, **_kwargs):
            if response is None:
                raise RuntimeError("Model service unavailable")
            return response

    repo = SQLiteRepository(tmp_path / "drafts.db")
    event = EngineeringEvent(event_id="REAL-AI-TEST", domain="rf", event_type="test", provenance={"source": "test"})
    analysis = AnalysisResult(event_id=event.event_id, processor="test", processor_version="1", findings=["Measured evidence"])

    with pytest.raises(KnowledgeGenerationUnavailable, match="No replacement draft"):
        KnowledgeService(repo, FailedModel(), PROJECT / "prompts").create_draft(event, analysis)

    assert repo.latest_draft_for_event(event.event_id) is None
    assert repo.list_knowledge() == []


def test_real_generation_still_preserves_observed_evidence(tmp_path):
    class Model:
        def chat(self, *_args, **_kwargs):
            return json.dumps({"summary": "AI interpretation requiring review.", "observations": ["Fabricated observation"]})

    repo = SQLiteRepository(tmp_path / "drafts.db")
    event = EngineeringEvent(event_id="REAL-AI-TEST", domain="rf", event_type="test", provenance={"source": "test"})
    analysis = AnalysisResult(event_id=event.event_id, processor="test", processor_version="1", findings=["Measured evidence"])

    draft = KnowledgeService(repo, Model(), PROJECT / "prompts").create_draft(event, analysis)

    assert draft.generated_by.startswith("configured_llm")
    assert draft.observations == ["Measured evidence"]
    assert draft.status == "draft"
    assert repo.get_draft(draft.draft_id) is not None


def test_draft_endpoint_returns_service_unavailable_without_audit(monkeypatch):
    from frib_ds.api import main as api

    audits = []
    repository = SimpleNamespace(get_event=lambda _id: object(), get_analysis=lambda _id: object(),
                                 record_audit=lambda *args: audits.append(args))

    def fail(*_args):
        raise KnowledgeGenerationUnavailable("No replacement draft was created.")

    services = SimpleNamespace(repo=repository, rag=SimpleNamespace(query=lambda *_args: None),
                               knowledge=SimpleNamespace(create_draft=fail))
    monkeypatch.setattr(api, "get_services", lambda: services)

    with pytest.raises(HTTPException) as failure:
        api.draft("REAL-AI-TEST")

    assert failure.value.status_code == 503
    assert "No replacement draft" in failure.value.detail
    assert audits == []
