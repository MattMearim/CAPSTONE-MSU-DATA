from frib_ds.rag.document_loader import DocumentLoader
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.llm import MockLLMProvider
from frib_ds.rag.service import RAGService
from frib_ds.rag.vector_store import MemoryVectorStore
from frib_ds.storage.documents import DocumentStore
from frib_ds.storage.sqlite import SQLiteRepository
import pytest


def test_configured_chunks_cover_long_paragraph_with_overlap(tmp_path):
    text = "abcdefghijklmnopqrstuvwxyz" * 13
    path = tmp_path / "reference.txt"
    path.write_text(text, encoding="utf-8")
    chunks = DocumentLoader(max_chars=80, overlap_chars=12).load(path)
    assert len(chunks) > 2
    assert all(len(chunk.text) <= 80 for chunk in chunks)
    reconstructed = chunks[0].text + "".join(chunk.text[12:] for chunk in chunks[1:])
    assert reconstructed == text


def test_zero_overlap_does_not_repeat_previous_paragraph(tmp_path):
    paragraphs = ["A" * 40, "B" * 40, "C" * 40]
    path = tmp_path / "reference.txt"
    path.write_text("\n\n".join(paragraphs), encoding="utf-8")
    assert [chunk.text for chunk in DocumentLoader(64, 0).load(path)] == paragraphs


def test_upload_and_rag_honor_shared_chunk_configuration(tmp_path):
    config = {"chunking": {"max_chars": 80, "overlap_chars": 8}}
    embedding = HashEmbeddingProvider(128)
    vector = MemoryVectorStore()
    repo = SQLiteRepository(tmp_path / "catalog.db")
    store = DocumentStore(tmp_path / "documents", repo, embedding, vector, config)
    uploaded = store.upload("reference.txt", b"RF cavity evidence " * 20, approved=True)
    rows = repo.approved_document_chunks()
    assert uploaded["indexed_chunks"] > 2
    assert len(rows) == uploaded["indexed_chunks"]
    assert all(len(chunk.text) <= 80 for chunk, _ in rows)
    rag = RAGService(embedding, vector, MockLLMProvider(), config, tmp_path)
    assert rag.loader.max_chars == 80 and rag.loader.overlap_chars == 8


@pytest.mark.parametrize("size,overlap", [(63, 0), (100001, 0), (64, -1), (64, 64)])
def test_invalid_chunk_configuration_is_rejected(size, overlap):
    with pytest.raises(ValueError, match="chunk"):
        DocumentLoader(size, overlap)
