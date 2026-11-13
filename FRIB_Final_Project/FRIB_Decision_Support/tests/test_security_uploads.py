"""Adversarial upload/storage regressions; all files live in pytest temporary data."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from frib_ds.ingestion import build_event
from frib_ds.ingestion.common import parse_datetime
from frib_ds.models import EngineeringEvent, Signal
from frib_ds.rag import document_loader
from frib_ds.rag.document_loader import DocumentLoader
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.rag.vector_store import MemoryVectorStore
from frib_ds.storage.documents import DocumentStore
from frib_ds.storage.files import EventFileStore
from frib_ds.storage.sqlite import SQLiteRepository
from test_mixed_api import environment


def event(event_id="EVIDENCE"):
    return EngineeringEvent(event_id=event_id, domain="other", event_type="evidence_record",
        provenance={"source": "security_test"})


def document_store(tmp_path):
    return DocumentStore(tmp_path / "documents", SQLiteRepository(tmp_path / "catalog.sqlite"),
        HashEmbeddingProvider(128), MemoryVectorStore())


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"])
def test_utc_boundary_overflow_is_rejected_as_invalid_evidence(value):
    with pytest.raises(ValueError, match="UTC date range"):
        parse_datetime(value)


@pytest.mark.parametrize("route", ["quality", "preview", "import"])
@pytest.mark.parametrize("filename,contents", [
    ("capture.csv", b"time,voltage [V]\n0001-01-01T00:00:00+23:59,1\n0001-01-01T00:00:01+23:59,2\n"),
    ("capture.log", b"0001-01-01T00:00:00+23:59 ERROR out-of-range timestamp\n"),
])
def test_boundary_timestamps_never_crash_api_or_write_partial_upload(environment, route, filename, contents):
    client, state, _ = environment
    response = client.post(f"/ingestion/{route}", files={"file": (filename, contents)},
        data={"options": '{"time_unit":"datetime"}', "validate": "true"})
    assert response.status_code in {200, 400}, response.text
    if response.status_code == 200:
        report = response.json()
        if route == "quality":
            assert report["status"] == "blocked"
        else:
            assert not report["validation"]["valid"]
    assert state["services"].repo.list_events() == []
    assert list(state["services"].files.event_dir.iterdir()) == []
    assert client.get("/health").status_code == 200


def test_strict_direct_import_refuses_truncated_quoted_csv():
    with pytest.raises(ValueError, match="quoting"):
        build_event("capture.csv", b'time [s],note\n0,"unterminated\n1,operator stopped\n')


def test_document_loader_stops_overlap_amplification_before_large_allocation(tmp_path, monkeypatch):
    monkeypatch.setattr(document_loader, "MAX_CHUNK_TEXT_CHARS", 2500)
    source = tmp_path / "overlap.txt"
    source.write_text("x" * 2000, encoding="utf-8")
    with pytest.raises(ValueError, match="reduce chunk overlap"):
        DocumentLoader(1000, 999).load(source)
    assert source.read_text(encoding="utf-8") == "x" * 2000


def test_last_full_chunk_does_not_emit_redundant_overlapping_suffixes(tmp_path):
    source = tmp_path / "overlap.txt"
    source.write_text("x" * 1001, encoding="utf-8")
    chunks = DocumentLoader(1000, 999).load(source)
    assert len(chunks) == 2
    assert [len(chunk.text) for chunk in chunks] == [1000, 1000]


@pytest.mark.parametrize("approved", [False, True])
def test_chunk_count_attack_rolls_back_catalog_index_and_original(tmp_path, monkeypatch, approved):
    monkeypatch.setattr(document_loader, "MAX_DOCUMENT_CHUNKS", 3)
    store = document_store(tmp_path)
    original = b"# First\n\n# Second\n\n# Third\n\n# Fourth\n"
    before = hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError, match="chunk limit"):
        store.upload("headings.md", original, approved=approved)
    assert store.repo.list_documents() == []
    assert store.repo.approved_document_chunks() == []
    assert list(store.directory.iterdir()) == []
    assert hashlib.sha256(original).hexdigest() == before


def test_pdf_extraction_limit_applies_across_pages_before_chunking(tmp_path, monkeypatch):
    source = tmp_path / "compressed.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(DocumentLoader, "_pdf_pages", staticmethod(lambda _: iter(["a" * 60, "b" * 60])))
    monkeypatch.setattr(document_loader, "MAX_EXTRACTED_CHARS", 100)
    with pytest.raises(ValueError, match="extracted text"):
        DocumentLoader().load(source)


def test_direct_loader_bounds_source_file_before_parsing(tmp_path, monkeypatch):
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 101)
    monkeypatch.setattr(document_loader, "MAX_SOURCE_BYTES", 100)
    with pytest.raises(ValueError, match="upload limit"):
        DocumentLoader().load(source)


def test_pdf_many_small_pages_share_one_chunk_budget(tmp_path, monkeypatch):
    source = tmp_path / "headings.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(DocumentLoader, "_pdf_pages", staticmethod(lambda _: iter(["First", "Second", "Third"])))
    monkeypatch.setattr(document_loader, "MAX_DOCUMENT_CHUNKS", 2)
    with pytest.raises(ValueError, match="chunk limit"):
        DocumentLoader().load(source)


def test_event_directory_alias_cannot_delete_a_sibling(tmp_path):
    store = EventFileStore(tmp_path / "events")
    original = store.save(event("VICTIM"))
    before = original.read_bytes()
    (store.event_dir / "ALIAS").symlink_to(store.directory("VICTIM"), target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        store.delete("ALIAS")
    assert original.read_bytes() == before


def test_document_directory_alias_cannot_delete_a_sibling(tmp_path):
    store = document_store(tmp_path)
    victim = store.upload("victim.txt", b"Keep the original procedure.")
    alias = store.upload("alias.txt", b"Independent procedure.")
    alias_dir = store._directory(alias["document_id"])
    (alias_dir / "original.txt").unlink()
    alias_dir.rmdir()
    victim_path, _ = store.original(victim["document_id"])
    alias_dir.symlink_to(victim_path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        store.delete(alias["document_id"])
    assert victim_path.read_bytes() == b"Keep the original procedure."
    assert store.repo.get_document(alias["document_id"]) is not None


@pytest.mark.parametrize("kind", ["event", "attachment", "document"])
def test_stored_original_symlinks_cannot_expose_outside_files(tmp_path, kind):
    secret = tmp_path / "outside-secret.txt"
    secret.write_bytes(b"outside file must never be served")
    if kind == "document":
        store = document_store(tmp_path)
        metadata = store.upload("reference.txt", b"Original")
        path, _ = store.original(metadata["document_id"])
        path.unlink()
        path.symlink_to(secret)
        accessor = lambda: store.original(metadata["document_id"])
    else:
        store = EventFileStore(tmp_path / "events")
        store.save(event())
        if kind == "event":
            path = store.original("EVIDENCE")
            accessor = lambda: store.original("EVIDENCE")
        else:
            metadata = store.save_attachment("EVIDENCE", "reference.csv", b"time,value\n0,1\n")
            path = store.attachment_path("EVIDENCE", metadata["file_id"])
            accessor = lambda: store.attachment_path("EVIDENCE", metadata["file_id"])
        path.unlink()
        path.symlink_to(secret)
    with pytest.raises(ValueError, match="symbolic link"):
        accessor()
    assert secret.read_bytes() == b"outside file must never be served"


def test_attachment_directory_symlink_cannot_redirect_new_upload(tmp_path):
    store = EventFileStore(tmp_path / "events")
    store.save(event())
    target = store.directory("EVIDENCE") / "other-files"
    target.mkdir()
    (store.directory("EVIDENCE") / "attachments").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        store.save_attachment("EVIDENCE", "capture.csv", b"time,value\n0,1\n")
    assert list(target.iterdir()) == []


def test_raw_event_signal_count_cannot_bypass_tabular_column_bound():
    signals = [Signal(name=f"sensor-{i}", sample_rate_hz=1, timestamps_s=[0, 1], values=[1, 2]) for i in range(65)]
    with pytest.raises(ValidationError, match="64"):
        EngineeringEvent(event_id="TOO-MANY-SIGNALS", domain="other", event_type="evidence_record",
            provenance={"source": "security_test"}, signals=signals)


@pytest.mark.parametrize("field", ["timestamps_s", "values"])
def test_raw_signal_cannot_bypass_sample_count_bound(field):
    values = {"name": "sensor", "sample_rate_hz": 1, "timestamps_s": [0, 1], "values": [1, 2]}
    values[field] = [0.0] * 250001
    with pytest.raises(ValidationError, match="250000"):
        Signal(**values)


def test_pathological_csv_header_does_not_backtrack_quadratically():
    # Run adversarial parsing in a child so a future regex regression cannot
    # freeze the test runner. The former pattern needs many seconds for this.
    import subprocess
    import sys
    script = (
        "from frib_ds.ingestion.tabular import header_details; "
        "header='sensor'+' '*100000+'x'; "
        "assert header_details(header)==(header,None)"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True,
        text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("header,expected", [
    ("voltage [mV]", ("voltage", "mV")),
    (" voltage (V)  ", ("voltage", "V")),
    ("reading [old] [Pa]", ("reading [old]", "Pa")),
    ("reading [future[unit]", ("reading", "future[unit")),
    ("reading [unsupported]", ("reading", "unsupported")),
    ("reading []", ("reading []", None)),
    ("reading", ("reading", None)),
])
def test_linear_header_parsing_preserves_explicit_unit_declarations(header, expected):
    from frib_ds.ingestion.tabular import header_details
    assert header_details(header) == expected


def test_pathological_unit_and_multiline_quantity_do_not_backtrack():
    import subprocess
    import sys
    script = """
from frib_ds.units import normalize_unit, parse_quantity, quantity_parts
from frib_ds.ingestion.quality import assess_upload
for parser, value in [(normalize_unit, 'V'+' '*100000+'x'), (parse_quantity, '1'+' '*100000+'x\\ny')]:
    try:
        parser(value)
    except ValueError:
        pass
    else:
        raise AssertionError('Malformed unit or quantity was accepted')
assert quantity_parts('1'+' '*100000+'x\\ny') is None
payload=('time [s],reading [V]\\n0,"1'+' '*100000+'x\\ny"\\n1,2\\n').encode()
assert assess_upload('attack.csv',payload)['status']=='blocked'
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True,
        text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("value,expected", [
    (" 1.5 kV ", ("1.5", "kV")), ("-2e-3 ms", ("-2e-3", "ms")),
    ("1 \n V", ("1", "V")), ("1 V\n/s", None),
    ("1", ("1", "")), (".5 m / s ^2", (".5", "m / s ^2")),
    ("1e", ("1", "e")), ("nonnumeric", None),
])
def test_quantity_lexing_keeps_numeric_prefix_and_unit_rules(value, expected):
    from frib_ds.units import quantity_parts
    assert quantity_parts(value) == expected
