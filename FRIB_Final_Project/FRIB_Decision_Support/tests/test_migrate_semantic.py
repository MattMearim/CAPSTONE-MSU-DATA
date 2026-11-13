"""One-time semantic copying preserves source evidence on success and failure."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from frib_ds import migrate_semantic as migration
from frib_ds.bootstrap import embedding_fingerprint
from frib_ds.models import EngineeringEvent
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.vector_store import SQLiteVectorStore
from frib_ds.storage.documents import DocumentStore
from frib_ds.storage.files import EventFileStore
from frib_ds.storage.reset import DataLifecycleLock
from frib_ds.storage.sqlite import SQLiteRepository


class SemanticFixture:
    """Explicit unit-test semantic stand-in; never selected by runtime code."""
    def embed(self, texts):
        return [[0.6, 0.8, 0.0] for _text in texts]


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and path.name != ".lifecycle.lock"}


@pytest.fixture
def source(tmp_path, monkeypatch):
    project = tmp_path / "project"
    config = project / "config"
    config.mkdir(parents=True)
    (config / "models.yaml").write_text("llm:\n  provider: ollama\nembeddings:\n  provider: sentence_transformers\n  model: all-MiniLM-L6-v2\nvector_store:\n  provider: sqlite\n")
    for variable in ("FRIB_LLM_PROVIDER", "FRIB_EMBEDDING_PROVIDER", "FRIB_EMBEDDING_MODEL", "FRIB_VECTOR_PROVIDER"):
        monkeypatch.delenv(variable, raising=False)
    data = project / "data"
    repo = SQLiteRepository(data / "frib.db")
    repo.ensure_embedding_compatibility(embedding_fingerprint({"provider": "hash", "dimensions": 32}))
    embeddings = HashEmbeddingProvider(32)
    vectors = SQLiteVectorStore(data / "chroma" / "vectors.sqlite")
    documents = DocumentStore(data / "documents", repo, embeddings, vectors)
    approved = documents.upload("approved.md", b"Review measured evidence and notify the designated response team.", approved=True)
    documents.upload("unapproved.md", b"Unreviewed notes must remain unapproved.", approved=False)
    event = EngineeringEvent(event_id="MIGRATION-EVENT", domain="other", event_type="review", provenance={"source": "test"})
    EventFileStore(data / "events").save(event)
    repo.save_event(event)
    (data / "logs").mkdir()
    (data / "logs" / "keep.log").write_text("Original application diagnostic")
    (data / "chroma" / "stale-old-index.bin").write_bytes(b"Old index should not be hydrated")
    with DataLifecycleLock(data):
        pass
    monkeypatch.setattr(migration, "build_embedding_provider", lambda _settings: SemanticFixture())
    return data, project / "data-local-ai", config, approved


def test_success_reembeds_copy_and_preserves_source_hash_catalog_and_originals(source):
    original, target, config, approved = source
    before = snapshot(original)

    receipt = migration.migrate_semantic(original, target, config)

    assert snapshot(original) == before
    assert receipt["source_preserved"] and receipt["approved_chunks_reembedded"] == 1
    source_repo = SQLiteRepository(original / "frib.db")
    copied = SQLiteRepository(target / "frib.db")
    assert json.loads(source_repo.metadata("embedding_fingerprint"))["provider"] == "hash"
    assert json.loads(copied.metadata("embedding_fingerprint"))["provider"] == "sentence_transformers"
    assert len(source_repo.approved_document_chunks()[0][1]) == 32
    assert copied.approved_document_chunks()[0][1] == [0.6, 0.8, 0.0]
    assert copied.data_counts() == source_repo.data_counts()
    assert copied.get_document(approved["document_id"]) == source_repo.get_document(approved["document_id"])
    for folder in ("documents", "events", "logs"):
        assert snapshot(target / folder) == snapshot(original / folder)
    assert not (target / "chroma" / "stale-old-index.bin").exists()
    store = SQLiteVectorStore(target / "chroma" / "vectors.sqlite")
    assert store.count() == 1
    assert store.search([0.6, 0.8, 0.0])[0][0].document_id == approved["document_id"]
    assert json.loads((target / "SEMANTIC_MIGRATION.json").read_text()) == receipt
    copied.ensure_embedding_compatibility(receipt["embedding_fingerprint"])


@pytest.mark.parametrize("result", [None, [], [[float("nan")]], [[True]], [[]]])
def test_failed_model_leaves_source_unchanged_and_no_destination(source, monkeypatch, result):
    original, target, config, _approved = source
    before = snapshot(original)

    class FailedModel:
        def embed(self, _texts):
            if result is None:
                raise RuntimeError("Download unavailable")
            return result

    monkeypatch.setattr(migration, "build_embedding_provider", lambda _settings: FailedModel())
    with pytest.raises((ValueError, RuntimeError)):
        migration.migrate_semantic(original, target, config)

    assert snapshot(original) == before
    assert not target.exists()
    assert list(target.parent.glob(".data-local-ai-migrating-*")) == []


def test_existing_destination_is_never_overwritten(source):
    original, target, config, _approved = source
    target.mkdir()
    (target / "keep.txt").write_text("User data")
    before = snapshot(original)
    with pytest.raises(FileExistsError):
        migration.migrate_semantic(original, target, config)
    assert (target / "keep.txt").read_text() == "User data"
    assert snapshot(original) == before


def test_destination_created_during_model_load_cannot_be_replaced_even_when_empty(source, monkeypatch):
    original, target, config, _approved = source
    before = snapshot(original)

    def load(_settings):
        target.mkdir()
        return SemanticFixture()

    monkeypatch.setattr(migration, "build_embedding_provider", load)
    with pytest.raises(OSError):
        migration.migrate_semantic(original, target, config)
    assert target.is_dir() and list(target.iterdir()) == []
    assert snapshot(original) == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_linked_database_is_refused_without_writing_source(source, tmp_path, kind):
    original, target, config, _approved = source
    database = original / "frib.db"
    external = tmp_path / "external.db"
    if kind == "symlink":
        database.rename(external)
        database.symlink_to(external)
    else:
        os.link(database, external)
    before = external.read_bytes()
    with pytest.raises(ValueError, match="linked|hardlinked"):
        migration.migrate_semantic(original, target, config)
    assert external.read_bytes() == before
    assert not target.exists()


def test_linked_original_is_refused(source, tmp_path):
    original, target, config, _approved = source
    external = tmp_path / "outside.txt"
    external.write_text("Outside content")
    (original / "documents" / "redirect.txt").symlink_to(external)
    with pytest.raises(ValueError, match="linked"):
        migration.migrate_semantic(original, target, config)
    assert external.read_text() == "Outside content" and not target.exists()


def test_pending_reset_and_busy_source_are_refused(source):
    original, target, config, _approved = source
    with DataLifecycleLock(original):
        with pytest.raises(RuntimeError, match="Stop it"):
            migration.migrate_semantic(original, target, config)
    repo = SQLiteRepository(original / "frib.db")
    with repo.connect() as connection:
        connection.execute("INSERT INTO repository_metadata VALUES('reset_pending','{}')")
    before = snapshot(original)
    with pytest.raises(ValueError, match="reset is pending"):
        migration.migrate_semantic(original, target, config)
    assert snapshot(original) == before and not target.exists()


@pytest.mark.parametrize("variable,value", [("FRIB_LLM_PROVIDER", "mock"), ("FRIB_EMBEDDING_PROVIDER", "hash"), ("FRIB_VECTOR_PROVIDER", "chroma")])
def test_nonreal_or_nonstandard_configuration_is_refused(source, monkeypatch, variable, value):
    original, target, config, _approved = source
    monkeypatch.setenv(variable, value)
    before = snapshot(original)
    with pytest.raises(ValueError):
        migration.migrate_semantic(original, target, config)
    assert snapshot(original) == before and not target.exists()


def test_factory_cannot_substitute_hash_under_semantic_configuration(source, monkeypatch):
    original, target, config, _approved = source
    monkeypatch.setattr(migration, "build_embedding_provider", lambda _settings: HashEmbeddingProvider())
    with pytest.raises(ValueError, match="Hash embeddings cannot"):
        migration.migrate_semantic(original, target, config)
    assert not target.exists()


def test_cli_failure_returns_nonzero_without_creating_destination(source, capsys):
    original, target, config, _approved = source
    target.mkdir()
    assert migration.main(["--source", str(original), "--destination", str(target), "--config-dir", str(config)]) == 1
    assert "never overwrites" in capsys.readouterr().err


def test_cli_success_returns_zero_and_receipt(source, capsys):
    original, target, config, _approved = source
    assert migration.main(["--source", str(original), "--destination", str(target), "--config-dir", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["destination"] == str(target)


def test_data_outside_project_and_nested_destination_are_refused(source, tmp_path):
    original, target, config, _approved = source
    for destination in (tmp_path / "data-ai", original / "data-ai"):
        with pytest.raises(ValueError, match="directly inside"):
            migration.migrate_semantic(original, destination, config)
        assert not destination.exists()
