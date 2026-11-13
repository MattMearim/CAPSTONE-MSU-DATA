"""Bound procedure decoding and catalog scans without changing saved evidence."""
import json
import tracemalloc

import pytest

from frib_ds.models import DocumentChunk
from frib_ds.rag.document_loader import DocumentLoader
from frib_ds.rag.vector_store import MemoryVectorStore, SQLiteVectorStore
from frib_ds.storage.sqlite import SQLiteRepository


def procedure_chunks(count):
    original = DocumentLoader().load("sample_docs/DEMO_ONLY_RF_PROCEDURE.md", approved=True)[0]
    return [original.model_copy(update={"chunk_id": f"PERF-{index}", "document_id": f"DOC-PERF{index:028d}"}) for index in range(count)]


@pytest.mark.parametrize("limit", [0, 1, 4, 50, -1])
def test_sqlite_retrieval_preserves_cosine_order_ties_zero_and_mixed_dimensions(tmp_path, limit):
    chunks = procedure_chunks(8)
    vectors = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [-1.0, 0.0], [0.0, 0.0], [1.0, 1.0], [1.0], [0.0, -1.0]]
    memory, sqlite = MemoryVectorStore(), SQLiteVectorStore(tmp_path / "vectors.sqlite")
    memory.add(chunks, vectors)
    sqlite.add(chunks, vectors)
    expected, actual = memory.search([1.0, 0.0], limit), sqlite.search([1.0, 0.0], limit)
    assert [chunk.chunk_id for chunk, _ in actual] == [chunk.chunk_id for chunk, _ in expected]
    assert [score for _, score in actual] == pytest.approx([score for _, score in expected], abs=1e-15)


def test_sqlite_retrieval_decodes_only_the_requested_hits(tmp_path, monkeypatch):
    chunks = procedure_chunks(120)
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    store.add(chunks, [[1.0, float(index)] for index in range(len(chunks))])
    decoded = []
    original = DocumentChunk.model_validate_json
    def validate(cls, payload, *args, **kwargs):
        decoded.append(payload)
        return original(payload, *args, **kwargs)
    monkeypatch.setattr(DocumentChunk, "model_validate_json", classmethod(validate))
    hits = store.search([1.0, 0.0], 3)
    assert [chunk.chunk_id for chunk, _ in hits] == ["PERF-0", "PERF-1", "PERF-2"]
    assert len(decoded) == 3


def test_other_workers_index_updates_deletions_and_reset_remain_visible(tmp_path):
    chunks = procedure_chunks(2)
    first = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    second = SQLiteVectorStore(first.path)
    first.add(chunks, [[1.0, 0.0], [0.0, 1.0]])
    assert first.search([1.0, 0.0], 1)[0][0].chunk_id == "PERF-0"
    second.add([chunks[1]], [[2.0, 0.0]])
    second.delete_document(chunks[0].document_id)
    assert first.search([1.0, 0.0], 1)[0][0].chunk_id == "PERF-1"
    second.clear()
    assert first.search([1.0, 0.0], 10) == []


def test_large_procedure_payloads_are_streamed_instead_of_loading_the_catalog_into_memory(tmp_path):
    chunks = procedure_chunks(512)
    chunks = [chunk.model_copy(update={"text": "Recorded procedure passage. " * 1300}) for chunk in chunks]
    store = SQLiteVectorStore(tmp_path / "large-vectors.sqlite")
    store.add(chunks, [[1.0, float(index)] for index in range(len(chunks))])
    tracemalloc.start()
    try:
        hits = store.search([1.0, 0.0], 3)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [chunk.chunk_id for chunk, _ in hits] == ["PERF-0", "PERF-1", "PERF-2"]
    # Catalog text exceeds 16 MiB; only a few hit payloads should be retained.
    assert peak < 4 * 1024 * 1024


def test_existing_catalog_gets_indexed_recent_event_lookup_without_changing_summaries(tmp_path):
    repository = SQLiteRepository(tmp_path / "catalog.sqlite")
    with repository.connect() as connection:
        connection.execute("DROP INDEX events_timestamp")
        for index in range(30):
            event = {"metadata": {"dataset_name": f"Dataset {index}", "unit_normalization": {"warnings": ["demo warning"]}},
                     "signals": [{"values": list(range(200))}], "states": [1, 2], "logs": ["demo"]}
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (f"EVENT-{index}", "rf", "synthetic", f"2026-01-01T00:{index:02d}:00", json.dumps(event)))
    # Reopening an existing workspace applies the additive indexes as well.
    repository = SQLiteRepository(repository.path)
    rows = repository.list_events(3)
    assert [row["event_id"] for row in rows] == ["EVENT-29", "EVENT-28", "EVENT-27"]
    assert all(row["signal_count"] == 1 and row["state_count"] == 2 and row["log_count"] == 1 and row["unit_warning_count"] == 1 for row in rows)
    assert rows[0]["dataset_name"] == "Dataset 29"
    assert all("payload" not in row for row in rows)
    with repository.connect() as connection:
        plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN SELECT event_id FROM events ORDER BY timestamp DESC LIMIT 3")]
    assert not any("TEMP B-TREE" in operation for operation in plan)
