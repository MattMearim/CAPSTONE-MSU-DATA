"""Reset deletes all workspace content and remains safe across failure/restart."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from frib_ds.api import main as api
from frib_ds.bootstrap import Services,get_services
from frib_ds.config import get_config
from frib_ds.storage import reset as reset_storage
from frib_ds.rag.vector_store import ChromaVectorStore


SECRET="UNIQUE-UPLOADED-CONTENT-MUST-DISAPPEAR-92841"


@pytest.fixture(params=["sqlite","memory"])
def environment(tmp_path,monkeypatch,request):
    monkeypatch.setenv("FRIB_DATA_DIR",str(tmp_path/"data"))
    monkeypatch.setenv("FRIB_CONFIG_DIR",str(Path("config").resolve()))
    monkeypatch.setenv("FRIB_LLM_PROVIDER","mock")
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER","hash")
    monkeypatch.setenv("FRIB_VECTOR_PROVIDER",request.param)
    get_config.cache_clear(); get_services.cache_clear()
    state={"services":Services()}
    monkeypatch.setattr(api,"get_services",lambda:state["services"])
    try:
        with TestClient(api.app) as client: yield client,state,tmp_path
    finally:
        get_config.cache_clear(); get_services.cache_clear()


def upload(client,approved=True):
    response=client.post("/documents/index",files={"file":("procedure.md",f"RF tuner pressure trip procedure. {SECRET}".encode(),"text/plain")},data={"approved":str(approved).lower()})
    assert response.status_code==200,response.text
    return response.json()


def populate(client,state,tmp_path):
    response=client.post("/events/generate",json={"domain":"rf","seed":101})
    assert response.status_code==200,response.text
    event_id=response.json()["event_id"]
    file_response=client.post(f"/events/{event_id}/files",files={"file":("operator.log",SECRET.encode(),"text/plain")})
    assert file_response.status_code==200,file_response.text
    assert client.post(f"/events/{event_id}/analyze").status_code==200
    draft=client.post(f"/events/{event_id}/draft").json()
    reviewed=client.post(f"/drafts/{draft['draft_id']}/review",json={"decision":"approve","reviewer":"test operator","comments":SECRET})
    assert reviewed.status_code==200,reviewed.text
    approved=upload(client); upload(client,False)
    s=state["services"]
    chunk,vector=s.repo.approved_document_chunks()[0]
    orphan=chunk.model_copy(update={"chunk_id":"orphan-retrieval-row","document_id":"DOC-orphan1234567890","text":SECRET})
    s.vector.add([orphan],[vector])
    for name in ("events","documents"):
        directory=tmp_path/"data"/name/"orphan-directory"
        directory.mkdir(); (directory/"unregistered.txt").write_text(SECRET,encoding="utf-8")
    (s.config.chroma_dir/"chroma.sqlite3").write_text(SECRET,encoding="utf-8")
    old_index=s.config.chroma_dir/"old-hnsw-directory"
    old_index.mkdir(); (old_index/"index.bin").write_bytes(SECRET.encode())
    return event_id,draft["draft_id"],approved["document_id"],file_response.json()["file_id"]


def assert_empty(client):
    status=client.get("/system/data")
    assert status.status_code==200,status.text
    assert status.json()["reset_pending"] is False
    counts=status.json()["counts"]
    assert counts["audit_entries"]==1
    assert all(value==0 for key,value in counts.items() if key!="audit_entries"),counts
    for path in ("/events","/documents","/knowledge","/knowledge/search?q=RF"):
        assert client.get(path).json()==[]
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip procedure"}).json()["sources"]==[]


@pytest.mark.parametrize("payload",[None,{}, {"confirmation":"reset"},{"confirmation":" RESET"},{"confirmation":True},{"confirmation":"RESET","unknown":1}])
def test_reset_requires_exact_explicit_confirmation_without_side_effects(environment,payload):
    client,state,_=environment
    assert client.post("/events/generate",json={"domain":"plc","seed":7}).status_code==200
    before=client.get("/system/data").json()
    response=client.post("/system/reset",json=payload)
    assert response.status_code==422,response.text
    assert client.get("/system/data").json()==before
    assert not state["services"].repo.pending_reset()


def test_reset_removes_all_levels_orphan_files_vectors_and_old_audits(environment):
    client,state,tmp_path=environment
    event_id,draft_id,document_id,file_id=populate(client,state,tmp_path)
    s=state["services"]
    fingerprint=s.repo.metadata("embedding_fingerprint")
    keep=tmp_path/"data"/"logs"/"keep.log"
    keep.parent.mkdir(); keep.write_text("Application diagnostic",encoding="utf-8")
    other=tmp_path/"sample_data"; other.mkdir(); (other/"keep.csv").write_text("1,2",encoding="utf-8")
    before=client.get("/system/data").json()["counts"]
    assert before["events"]==1 and before["documents"]==2
    assert all(before[key]>0 for key in ("analyses","drafts","reviews","knowledge","document_chunks","event_files","stored_files","retrieval_vectors","legacy_index_files"))
    reset=client.post("/system/reset",json={"confirmation":"RESET"})
    assert reset.status_code==200,reset.text
    receipt=reset.json()
    assert receipt["reset"] is True and receipt["removed"]==before
    assert receipt["reset_id"].startswith("RESET-")
    assert_empty(client)
    assert s.repo.metadata("embedding_fingerprint")==fingerprint
    assert s.repo.deleted_document_ids()==[]
    assert list(s.config.event_dir.iterdir())==[] and list(s.config.document_dir.iterdir())==[]
    assert not (s.config.chroma_dir/"chroma.sqlite3").exists()
    assert not (s.config.chroma_dir/"old-hnsw-directory").exists()
    assert keep.read_text(encoding="utf-8")=="Application diagnostic"
    assert (other/"keep.csv").read_text(encoding="utf-8")=="1,2"
    assert SECRET.encode() not in s.repo.path.read_bytes()
    if hasattr(s.vector,"path"): assert SECRET.encode() not in s.vector.path.read_bytes()
    audit=client.get("/audit").json()
    assert len(audit)==1 and audit[0]["action"]=="reset"
    assert audit[0]["details"]=={"removed":before}
    for path in (f"/events/{event_id}",f"/events/{event_id}/analysis",f"/drafts/{draft_id}",f"/documents/{document_id}/download",f"/events/{event_id}/files/{file_id}/download"):
        assert client.get(path).status_code==404,path
    state["services"]=Services()
    assert_empty(client)
    repeated=client.post("/system/reset",json={"confirmation":"RESET"})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()["reset_id"]!=receipt["reset_id"]
    assert repeated.json()["removed"]["audit_entries"]==1
    assert_empty(client)


def test_four_level_lifecycle_still_works_after_reset_and_restart(environment):
    client,state,_=environment
    upload(client)
    assert client.post("/system/reset",json={"confirmation":"RESET"}).status_code==200
    state["services"]=Services()
    doc=upload(client)
    response=client.post("/events/generate",json={"domain":"rf","seed":101})
    assert response.status_code==200,response.text
    event_id=response.json()["event_id"]
    analysis=client.post(f"/events/{event_id}/analyze")
    assert analysis.status_code==200 and analysis.json()["features"]
    query=client.post("/rag/query",json={"question":"RF tuner pressure trip procedure","event_id":event_id})
    assert query.status_code==200 and query.json()["sources"][0]["document_id"]==doc["document_id"]
    draft=client.post(f"/events/{event_id}/draft")
    assert draft.status_code==200,draft.text
    reviewed=client.post(f"/drafts/{draft.json()['draft_id']}/review",json={"decision":"approve","reviewer":"human reviewer","comments":"Reviewed synthetic evidence after reset"})
    assert reviewed.status_code==200 and reviewed.json()["knowledge"]
    state["services"]=Services()
    assert len(client.get("/knowledge").json())==1
    assert len(client.get("/documents").json())==1
    assert client.get(f"/events/{event_id}/analysis").status_code==200


@pytest.mark.parametrize("resume",["retry","restart"])
def test_failed_cleanup_is_not_successful_and_resumes_before_retrieval(environment,monkeypatch,resume):
    client,state,tmp_path=environment
    populate(client,state,tmp_path)
    s=state["services"]; original_clear=s.vector.clear
    def fail(): raise OSError("Simulated index cleanup interruption")
    monkeypatch.setattr(s.vector,"clear",fail)
    failed=client.post("/system/reset",json={"confirmation":"RESET"})
    assert failed.status_code==503,failed.text
    pending=s.repo.pending_reset()
    assert pending and client.get("/system/data").json()["reset_pending"]
    assert client.get("/health").status_code==200
    assert client.get("/events").status_code==503
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip procedure"}).status_code==503
    assert s.repo.data_counts()["documents"]==0
    assert list(s.config.document_dir.iterdir())
    if resume=="retry":
        monkeypatch.setattr(s.vector,"clear",original_clear)
        retried=client.post("/system/reset",json={"confirmation":"RESET"})
        assert retried.status_code==200,retried.text
        assert retried.json()["reset_id"]==pending["reset_id"]
    else: state["services"]=Services()
    assert_empty(client)


@pytest.mark.parametrize("root_name",["events","documents","chroma"])
def test_reparse_point_is_rejected_before_catalog_or_files_are_deleted(environment,monkeypatch,root_name):
    client,state,tmp_path=environment
    assert client.post("/events/generate",json={"domain":"plc","seed":3}).status_code==200
    upload(client)
    s=state["services"]; before=s.repo.data_counts()
    target=tmp_path/"data"/root_name/"junction-object"
    target.mkdir(); secret=target/"outside.txt"; secret.write_text(SECRET,encoding="utf-8")
    original_lstat=Path.lstat
    class JunctionStat:
        st_file_attributes=0x400
        def __init__(self,wrapped): self.wrapped=wrapped
        def __getattr__(self,key): return getattr(self.wrapped,key)
    def lstat(path,*args,**kwargs):
        result=original_lstat(path,*args,**kwargs)
        return JunctionStat(result) if path==target else result
    monkeypatch.setattr(Path,"lstat",lstat)
    response=client.post("/system/reset",json={"confirmation":"RESET"})
    assert response.status_code==409,response.text
    assert "reparse" in response.text
    assert s.repo.data_counts()==before and s.repo.pending_reset() is None
    assert secret.read_text(encoding="utf-8")==SECRET


def test_redirected_event_root_is_refused_before_mutation(environment,monkeypatch):
    client,state,tmp_path=environment
    assert client.post("/events/generate",json={"domain":"plc","seed":3}).status_code==200
    s=state["services"]; before=s.repo.data_counts()
    outside=tmp_path/"outside"/"events"; outside.mkdir(parents=True)
    sentinel=outside/"keep.txt"; sentinel.write_text(SECRET,encoding="utf-8")
    monkeypatch.setattr(s.config,"event_dir",outside)
    response=client.post("/system/reset",json={"confirmation":"RESET"})
    assert response.status_code==409,response.text
    assert s.repo.data_counts()==before and sentinel.read_text(encoding="utf-8")==SECRET


def test_redirected_sqlite_index_is_refused_before_any_data_mutation(environment,monkeypatch,tmp_path):
    client,state,_=environment
    s=state["services"]
    if not hasattr(s.vector,"path"):
        monkeypatch.setitem(s.config.models["vector_store"],"provider","sqlite")
        state["services"]=s=Services()
    assert client.post("/events/generate",json={"domain":"plc","seed":13}).status_code==200
    before=s.repo.data_counts()
    outside=tmp_path/"shared-index.sqlite"; outside.write_bytes(SECRET.encode())
    monkeypatch.setattr(s.vector,"path",outside)
    response=client.post("/system/reset",json={"confirmation":"RESET"})
    assert response.status_code==409,response.text
    assert "outside" in response.text
    assert s.repo.data_counts()==before and outside.read_bytes()==SECRET.encode()


def test_inflight_upload_finishes_before_reset_and_cannot_restore_content(environment,monkeypatch):
    client,state,_=environment
    entered=Event(); release=Event()
    original_upload=state["services"].documents.upload
    def slow(*args,**kwargs):
        entered.set()
        if not release.wait(10): raise TimeoutError("Upload test did not release")
        return original_upload(*args,**kwargs)
    monkeypatch.setattr(state["services"].documents,"upload",slow)
    with ThreadPoolExecutor(max_workers=3) as pool:
        in_flight=pool.submit(upload,client)
        try:
            assert entered.wait(5)
            reset=pool.submit(client.post,"/system/reset",json={"confirmation":"RESET"})
            assert pool.submit(client.get,"/health").result(timeout=3).status_code==200
            assert not reset.done(),"Reset must wait for an in-flight data request"
        finally: release.set()
        assert in_flight.result(timeout=5)["indexed_chunks"]>0
        reset_response=reset.result(timeout=5)
    assert reset_response.status_code==200,reset_response.text
    assert reset_response.json()["removed"]["documents"]==1
    state["services"]=Services()
    assert_empty(client)


def test_cached_second_worker_drops_stale_memory_retrieval_after_reset(environment):
    client,state,_=environment
    upload(client)
    second_worker=Services()
    assert second_worker.vector.count()>0
    assert client.post("/system/reset",json={"confirmation":"RESET"}).status_code==200
    state["services"]=second_worker
    assert client.get("/system/data").json()["counts"]["retrieval_vectors"]==0
    assert client.post("/rag/query",json={"question":"RF tuner pressure trip procedure"}).json()["sources"]==[]
    assert_empty(client)


def test_switching_to_memory_reset_clears_inactive_sqlite_and_cannot_resurrect(environment,monkeypatch):
    client,state,_=environment
    monkeypatch.setitem(state["services"].config.models["vector_store"],"provider","sqlite")
    state["services"]=Services()
    upload(client)
    sqlite_path=state["services"].vector.path
    assert sqlite_path.is_file()
    monkeypatch.setitem(state["services"].config.models["vector_store"],"provider","memory")
    state["services"]=Services()
    assert client.post("/system/reset",json={"confirmation":"RESET"}).status_code==200
    assert not sqlite_path.exists()
    monkeypatch.setitem(state["services"].config.models["vector_store"],"provider","sqlite")
    state["services"]=Services()
    assert_empty(client)


def test_chroma_clear_removes_orphan_entries_in_batches_without_model_dependency():
    class Collection:
        name="active-frib"
        def __init__(self): self.ids=[f"orphan-{index}" for index in range(2003)]; self.deleted=[]
        def get(self,limit,include): return {"ids":self.ids[:limit]}
        def delete(self,ids): self.deleted.extend(ids); self.ids=[item for item in self.ids if item not in ids]
        def count(self): return len(self.ids)
    vector=ChromaVectorStore.__new__(ChromaVectorStore); vector.collection=Collection()
    class Client:
        def __init__(self): self.deleted=[]
        def list_collections(self): return ["old-frib-collection",vector.collection]
        def delete_collection(self,name): self.deleted.append(name)
    vector.client=Client()
    vector.clear()
    assert vector.count()==0 and len(vector.collection.deleted)==2003
    assert vector.client.deleted==["old-frib-collection"]
