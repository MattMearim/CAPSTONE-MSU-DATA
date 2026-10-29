from pathlib import Path
from frib_ds.rag.document_loader import DocumentLoader
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.vector_store import MemoryVectorStore

def test_approved_chunk_can_be_retrieved():
    loader=DocumentLoader(); chunks=loader.load(Path("sample_docs/DEMO_ONLY_RF_PROCEDURE.md"),approved=True)
    emb=HashEmbeddingProvider(128); store=MemoryVectorStore(); store.add(chunks,emb.embed([c.text for c in chunks]))
    hits=store.search(emb.embed(["reflected power tuner pressure trip"])[0],top_k=3)
    assert hits and hits[0][0].approved
