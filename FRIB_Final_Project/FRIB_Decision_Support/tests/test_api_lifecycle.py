"""Temporary-data API tests for durable evidence and human review boundaries."""
from __future__ import annotations

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from frib_ds.api import main as api
from frib_ds import bootstrap
from frib_ds.bootstrap import Services, get_services
from frib_ds.config import get_config
from frib_ds.rag.embeddings import HashEmbeddingProvider
from frib_ds.storage.documents import DocumentStore


@pytest.fixture(params=["sqlite","memory"])
def api_environment(tmp_path,monkeypatch,request):
    monkeypatch.setenv("FRIB_DATA_DIR",str(tmp_path/"data"))
    monkeypatch.setenv("FRIB_CONFIG_DIR",str(Path("config").resolve()))
    monkeypatch.setenv("FRIB_LLM_PROVIDER","mock")
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER","hash")
    monkeypatch.setenv("FRIB_VECTOR_PROVIDER",request.param)
    get_config.cache_clear(); get_services.cache_clear()
    state={"services":Services()}
    monkeypatch.setattr(api,"get_services",lambda:state["services"])
    with TestClient(api.app) as client:
        yield client,state,tmp_path
    get_config.cache_clear(); get_services.cache_clear()


def upload(client,filename="rf.md",content=b"RF tuner pressure trip reflected power procedure.\n",approved=True):
    return client.post("/documents/index",files={"file":(filename,content,"text/plain")},data={"approved":str(approved).lower(),"title":"RF operating reference","version":"1.2"})


def test_services_are_initialized_before_accepting_requests(monkeypatch):
    calls=[]
    monkeypatch.setattr(api,"get_services",lambda:calls.append("initialized"))
    with TestClient(api.app):
        assert calls==["initialized"]


def test_long_document_processing_keeps_health_responsive(api_environment,monkeypatch):
    client,state,_=api_environment
    started=Event(); release=Event()
    original_upload=state["services"].documents.upload
    def slow_upload(*args,**kwargs):
        started.set()
        if not release.wait(10): raise TimeoutError("Test upload was not released")
        return original_upload(*args,**kwargs)
    monkeypatch.setattr(state["services"].documents,"upload",slow_upload)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_upload=executor.submit(upload,client)
        try:
            assert started.wait(5),"Document processing did not start"
            health=executor.submit(client.get,"/health").result(timeout=3)
            assert health.status_code==200
        finally:
            release.set()
        assert pending_upload.result(timeout=5).status_code==200


def test_approved_original_index_and_deletion_survive_restart(api_environment):
    client,state,tmp_path=api_environment
    content=b"RF tuner pressure trip reflected power procedure.\n"
    response=upload(client,content=content)
    assert response.status_code==200,response.text
    metadata=response.json(); document_id=metadata["document_id"]
    assert metadata["checksum"]==hashlib.sha256(content).hexdigest()
    assert metadata["size_bytes"]==len(content) and metadata["indexed_chunks"]>0
    assert metadata["version"]=="1.2" and metadata["approval_metadata"]["explicitly_approved"]
    assert client.get(f"/documents/{document_id}/download").content==content
    assert client.get("/documents").json()==[metadata]
    rows=state["services"].repo.approved_document_chunks()
    assert rows and rows[0][0].source_path==f"document:{document_id}/rf.md"
    state["services"]=Services()
    query=client.post("/rag/query",json={"question":"RF tuner pressure trip reflected power procedure."})
    assert query.status_code==200,query.text
    assert query.json()["sources"][0]["document_id"]==document_id
    assert client.delete(f"/documents/{document_id}").status_code==200
    state["services"]=Services()
    assert client.get("/documents").json()==[]
    assert client.get(f"/documents/{document_id}/download").status_code==404
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip reflected power procedure."}).json()["sources"]==[]
    assert not (tmp_path/"data"/"documents"/document_id).exists()
    actions=[entry["action"] for entry in client.get("/audit").json()]
    assert actions==["delete","upload"]


def test_unapproved_original_remains_outside_retrieval(api_environment):
    client,state,_=api_environment
    response=upload(client,approved=False)
    assert response.status_code==200,response.text
    metadata=response.json()
    assert not metadata["approved"] and metadata["indexed_chunks"]==0
    state["services"]=Services()
    assert client.get("/documents").json()[0]["document_id"]==metadata["document_id"]
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip reflected power procedure."}).json()["sources"]==[]
    assert client.get(f'/documents/{metadata["document_id"]}/download').content.startswith(b"RF tuner")


def test_interrupted_document_delete_cannot_restore_retrieval(api_environment,monkeypatch):
    client,state,tmp_path=api_environment
    response=upload(client); document_id=response.json()["document_id"]
    store=state["services"].documents
    def interrupted(_document_id): raise OSError("Simulated index outage during deletion")
    monkeypatch.setattr(store.vector,"delete_document",interrupted)
    with pytest.raises(OSError,match="Simulated"):
        store.delete(document_id)
    state["services"]=Services()
    assert client.get("/documents").json()==[]
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip reflected power procedure."}).json()["sources"]==[]
    assert not (tmp_path/"data"/"documents"/document_id).exists()


@pytest.mark.parametrize("filename,content",[("empty.txt",b""),("empty.md",b" \n\t"),("wrong.exe",b"text"),("../outside.txt",b"text"),("broken.pdf",b"not a PDF"),("binary.txt",b"\xff\x00")])
def test_invalid_uploads_leave_no_catalog_or_files(api_environment,filename,content):
    client,state,tmp_path=api_environment
    response=upload(client,filename,content)
    assert response.status_code==400,response.text
    assert client.get("/documents").json()==[]
    assert list((tmp_path/"data"/"documents").iterdir())==[]


def test_document_store_rejects_windows_paths():
    # Multipart parsers may reduce a browser's Windows path to its basename.
    with pytest.raises(ValueError,match="filesystem path"):
        DocumentStore.validate_filename("C:\\private\\secret.txt")


@pytest.mark.parametrize("settings",[{"dimensions":128},{"provider":"sentence_transformers","model":"other-model"}])
def test_populated_catalog_rejects_embedding_changes_before_loading_model(api_environment,monkeypatch,settings):
    client,state,_=api_environment
    assert upload(client).status_code==200
    for key,value in settings.items(): monkeypatch.setitem(state["services"].config.models["embeddings"],key,value)
    def unexpected_model_load(_config): raise AssertionError("Embedding model must not load before compatibility check")
    monkeypatch.setattr(bootstrap,"build_embedding_provider",unexpected_model_load)
    with pytest.raises(ValueError,match="separate FRIB_DATA_DIR"):
        Services()


def test_same_dimension_model_change_is_rejected(api_environment,monkeypatch):
    client,state,_=api_environment
    settings=state["services"].config.models["embeddings"]
    monkeypatch.setitem(settings,"provider","sentence_transformers")
    monkeypatch.setitem(settings,"model","model-a")
    # Use a local stand-in: the compatibility check must use identity rather
    # than dimension equality and must never download a model in this test.
    monkeypatch.setattr(bootstrap,"build_embedding_provider",lambda _config:HashEmbeddingProvider(384))
    state["services"]=Services()
    assert upload(client).status_code==200
    monkeypatch.setitem(settings,"model","model-b")
    with pytest.raises(ValueError,match="different or unknown embedding settings"):
        Services()


def test_tokenizer_version_and_missing_identity_are_rejected(api_environment,monkeypatch):
    client,state,_=api_environment
    assert upload(client).status_code==200
    monkeypatch.setattr(bootstrap,"embedding_fingerprint",lambda _config:{"provider":"hash","dimensions":384,"tokenizer_version":3})
    with pytest.raises(ValueError,match="tokenizer version"):
        Services()
    with state["services"].repo.connect() as connection:
        connection.execute("DELETE FROM repository_metadata WHERE key='embedding_fingerprint'")
    with pytest.raises(ValueError,match="unknown embedding settings"):
        Services()


def test_empty_approved_catalog_adopts_new_identity_and_ignores_legacy_chroma(api_environment,monkeypatch):
    client,state,_=api_environment
    assert upload(client,approved=False).status_code==200
    config=state["services"].config
    legacy=config.chroma_dir/"chroma.sqlite3"
    legacy.write_bytes(b"Uncataloged legacy Chroma data must not block a fresh index")
    monkeypatch.setitem(config.models["embeddings"],"dimensions",128)
    state["services"]=Services()
    assert state["services"].embedding.dimensions==128
    with state["services"].repo.connect() as connection:
        row=connection.execute("SELECT value FROM repository_metadata WHERE key='embedding_fingerprint'").fetchone()
    assert '"dimensions":128' in row["value"] and '"tokenizer_version":2' in row["value"]
    assert legacy.read_bytes()==b"Uncataloged legacy Chroma data must not block a fresh index"


def test_upload_limit_is_enforced_before_indexing(api_environment,monkeypatch):
    client,_,_=api_environment
    monkeypatch.setattr(api,"MAX_DOCUMENT_BYTES",8)
    assert upload(client,content=b"123456789").status_code==413
    assert client.get("/documents").json()==[]


def test_pdf_original_and_blank_pdf_validation(api_environment):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    client,_,_=api_environment
    writer=PdfWriter(); page=writer.add_blank_page(width=300,height=300)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
    stream=DecodedStreamObject(); stream.set_data(b"BT /F1 12 Tf 10 100 Td (RF tuner pressure procedure) Tj ET")
    page[NameObject("/Contents")]=writer._add_object(stream)
    output=io.BytesIO(); writer.write(output); content=output.getvalue()
    response=upload(client,"reference.pdf",content)
    assert response.status_code==200,response.text
    assert client.get(f'/documents/{response.json()["document_id"]}/download').content==content
    blank=PdfWriter(); blank.add_blank_page(width=300,height=300)
    empty=io.BytesIO(); blank.write(empty)
    assert upload(client,"blank.pdf",empty.getvalue()).status_code==400


def test_event_original_attachments_review_and_cascade_delete(api_environment):
    client,state,tmp_path=api_environment
    generated=client.post("/events/generate",json={"domain":"rf","seed":42})
    assert generated.status_code==200,generated.text
    event=generated.json(); event_id=event["event_id"]
    event_row=next(row for row in client.get("/events").json() if row["event_id"]==event_id)
    assert event_row["signal_count"]==len(event["signals"])
    assert event_row["dataset_name"]==event["metadata"].get("dataset_name")
    duplicate=dict(event); duplicate["metadata"]={"tampered":True}
    assert client.post("/events",json=duplicate).status_code==409
    original=client.get(f"/events/{event_id}/download")
    assert original.json()["event_id"]==event_id
    assert original.json()["signals"][0]["unit"]=="normalized"
    assert event["signals"][0]["unit"]=="1"
    stored_checksum=(tmp_path/"data"/"events"/event_id/"sha256.txt").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(original.content).hexdigest()==stored_checksum
    assert original.content==state["services"].files.original(event_id).read_bytes()
    assert client.get(f"/events/{event_id}/download?format=normalized-json").json()==event
    csv_response=client.get(f"/events/{event_id}/download?format=csv")
    assert csv_response.status_code==200 and "timestamp_s" in csv_response.text
    raw=b"time,value\r\n0,0.1\r\n1,0.2\r\n"
    file_response=client.post(f"/events/{event_id}/files",files={"file":("original.csv",raw,"text/csv")})
    assert file_response.status_code==200,file_response.text
    metadata=file_response.json(); file_id=metadata["file_id"]
    assert metadata["checksum"]==hashlib.sha256(raw).hexdigest()
    assert client.get(f"/events/{event_id}/files/{file_id}/download").content==raw
    assert client.post(f"/events/{event_id}/analyze").status_code==200
    draft_response=client.post(f"/events/{event_id}/draft")
    assert draft_response.status_code==200,draft_response.text
    draft_id=draft_response.json()["draft_id"]
    review=client.post(f"/drafts/{draft_id}/review",json={"decision":"approve","reviewer":"test operator","comments":"Reviewed synthetic evidence"})
    assert review.status_code==200,review.text
    state["services"]=Services()
    assert client.get(f"/events/{event_id}/draft").json()["status"]=="approved"
    assert client.get(f"/events/{event_id}/files").json()==[metadata]
    assert client.get(f"/events/{event_id}/files/{file_id}/download").content==raw
    assert len(client.get("/knowledge").json())==1
    assert client.delete(f"/events/{event_id}").status_code==200
    state["services"]=Services()
    for suffix in ("","/analysis","/draft","/files",f"/files/{file_id}/download"):
        assert client.get(f"/events/{event_id}{suffix}").status_code==404
    assert client.get(f"/drafts/{draft_id}").status_code==404
    assert client.get("/knowledge").json()==[]
    assert not (tmp_path/"data"/"events"/event_id).exists()
    assert any(entry["action"]=="review" for entry in client.get("/audit").json())


def test_attachment_delete_does_not_change_original_event(api_environment):
    client,_,_=api_environment
    event=client.post("/events/generate",json={"domain":"plc","seed":17}).json()
    event_id=event["event_id"]
    response=client.post(f"/events/{event_id}/files",files={"file":("note.log",b"Operator observation\n","text/plain")})
    assert response.status_code==200,response.text
    file_id=response.json()["file_id"]
    assert client.delete(f"/events/{event_id}/files/{file_id}").status_code==200
    assert client.get(f"/events/{event_id}/files").json()==[]
    assert client.get(f"/events/{event_id}").json()==event
    assert client.get(f"/events/{event_id}/files/{file_id}/download").status_code==404
