from __future__ import annotations

import csv
import io
import sqlite3
import mimetypes
import json
import hashlib
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, Response
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from frib_ds.bootstrap import get_services
from frib_ds.models import EngineeringEvent, GenerateEventRequest, GenerateCustomEventRequest, RAGQueryRequest, ReviewRequest, UnitConversionRequest, QualityReviewRequest, ResetDataRequest
from frib_ds.storage.documents import MAX_DOCUMENT_BYTES, DocumentStore
from frib_ds.storage.reset import DataLifecycleLock,UnsafeResetPath
from frib_ds.config import get_config
from frib_ds.units import unit_catalog, normalize_unit, convert_value, normalize_event_units
from frib_ds.system_manager import get_system_manager

@asynccontextmanager
async def lifespan(_app:FastAPI):
    # Finish model/index initialization before accepting concurrent requests.
    await run_in_threadpool(get_services)
    yield


app=FastAPI(title="FRIB Field-Agnostic Decision-Support POC",version="0.4.0",description="Human-supervised engineering decision support with data-quality review, explicit repairs and deterministic unit conversion. Synthetic/demo outputs are not facility operating instructions.",lifespan=lifespan)


class DataLifecycleMiddleware:
    """Serialize content requests and resets through their complete response.

    Health, catalogs and pure upload previews stay responsive. The OS lock also
    prevents another local worker from committing an old upload after reset.
    """
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        path=scope.get("path","")
        pure_system=path in {"/system/info","/system/versions/check","/system/upgrades/plan"}
        guarded=scope["type"]=="http" and not pure_system and any(path==prefix or path.startswith(prefix+"/") for prefix in ("/events","/documents","/rag","/drafts","/knowledge","/audit","/system","/ingestion/import"))
        if not guarded:
            await self.app(scope,receive,send); return
        # Initialize before acquiring the request lock: startup hydration uses
        # the same OS lock and must also work for clients without ASGI lifespan.
        services=await run_in_threadpool(get_services)
        lock=DataLifecycleLock(get_config().data_dir)
        try:
            while not lock.try_acquire(): await asyncio.sleep(0.01)
            if path not in {"/system/reset","/system/data"} and not await run_in_threadpool(services.refresh_data_state):
                response=JSONResponse({"detail":"A data reset is incomplete. Retry Reset project data or restart the API to finish cleanup."},status_code=503)
                await response(scope,receive,send); return
            await self.app(scope,receive,send)
        finally: lock.close()


app.add_middleware(DataLifecycleMiddleware)


class UpgradePlanRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mode:Literal["required","selected"]="required"
    components:list[str]=Field(default_factory=list,max_length=13)
    upgrade_pip:StrictBool=False
    upgrade_python:StrictBool=False
    include_semantic:StrictBool=False


class VersionCheckRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")


@app.get("/system/info")
def system_info():
    try: return get_system_manager().inventory()
    except (ValueError,OSError) as exc: raise HTTPException(409,str(exc))


@app.post("/system/versions/check")
def check_system_versions(req:VersionCheckRequest|None=None):
    # Only this explicit action contacts official PyPI; no inventory GET does.
    return get_system_manager().check_latest_versions()


@app.post("/system/upgrades/plan")
def queue_system_upgrade(req:UpgradePlanRequest):
    try: return get_system_manager().queue_plan(req.model_dump())
    except ValueError as exc: raise HTTPException(400,str(exc))
    except OSError as exc: raise HTTPException(503,"Could not save the next-start upgrade plan. Check workspace write permissions and try again.") from exc


@app.delete("/system/upgrades/plan")
def cancel_system_upgrade():
    try: return get_system_manager().cancel_plan()
    except ValueError as exc: raise HTTPException(409,str(exc))
    except OSError as exc: raise HTTPException(503,"Could not cancel the upgrade plan. Check workspace write permissions and try again.") from exc


@app.get("/system/data")
def system_data():
    try:
        services=get_services()
        services.refresh_data_state()
        return services.data_status()
    except UnsafeResetPath as exc: raise HTTPException(409,str(exc))


@app.post("/system/reset")
def reset_system_data(req:ResetDataRequest):
    try: return get_services().reset_data()
    except UnsafeResetPath as exc: raise HTTPException(409,str(exc))
    except Exception as exc:
        # A committed pending intent survives failures; content requests are
        # blocked until retry or startup finishes all remaining cleanup.
        raise HTTPException(503,"Reset cleanup did not finish. Retry Reset project data or restart the API; uploaded content remains unavailable until cleanup succeeds.") from exc


def _store_event(s,event:EngineeringEvent):
    if s.repo.get_event(event.event_id):
        raise HTTPException(409,"This event ID already exists. Use a new ID to preserve the original evidence.")
    # Metadata is intentionally flexible, but Pydantic serializes nonfinite
    # floats in Any-valued fields as null. Reject them before preserving bytes
    # or catalog rows so the stored evidence cannot silently change meaning.
    try:
        metadata=[event.metadata,*[record.metadata for records in (event.signals,event.states,event.logs) for record in records]]
        json.dumps(metadata,allow_nan=False,default=str)
    except ValueError as exc:
        raise HTTPException(400,"Event values and nested metadata must contain finite JSON numbers; replace NaN/Infinity with explicit missing-data notes.") from exc
    try:
        from frib_ds.quality import assess_event
        normalized=normalize_event_units(event)
        normalized.metadata["data_quality"]=assess_event(normalized,normalized.metadata.get("quality_expectations"))
    except ValueError as exc: raise HTTPException(400,str(exc))
    try:
        s.files.save(event)
    except FileExistsError:
        raise HTTPException(409,"Original evidence already exists for this event ID. Use a new ID.")
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    try:
        s.repo.save_event(normalized)
    except sqlite3.IntegrityError:
        s.files.delete(event.event_id)
        raise HTTPException(409,"This event ID already exists. Use a new ID.")
    except Exception:
        s.files.delete(event.event_id)
        raise
    s.repo.record_audit("create","event",event.event_id,{"domain":event.domain,"source":event.provenance.source})
    return normalized


@app.get("/health")
def health():
    s=get_services()
    return {"status":"ok","llm_provider":s.config.models.get("llm",{}).get("provider"),"embedding_provider":s.config.models.get("embeddings",{}).get("provider"),"vector_provider":s.config.models.get("vector_store",{}).get("provider"),"domains":s.processors.domains()}


@app.get("/generators")
def generators():
    return get_services().generators.describe()


@app.get("/units")
def units():
    return unit_catalog()


@app.post("/units/convert")
def convert_units(req:UnitConversionRequest):
    try:
        source=normalize_unit(req.from_unit); target=normalize_unit(req.to_unit)
        converted=convert_value(req.value,source,target)
    except ValueError as exc: raise HTTPException(400,str(exc))
    dimension=next(unit["dimension"] for unit in unit_catalog() if unit["symbol"]==source)
    return {"value":req.value,"from_unit":source,"to_unit":target,"converted_value":converted,"dimension":dimension}


def _import_options(options:str)->dict:
    if len(options)>100000: raise ValueError("Import settings are too large")
    try: parsed=json.loads(options)
    except (ValueError,TypeError) as exc: raise ValueError("Import settings must be a valid JSON object") from exc
    if not isinstance(parsed,dict): raise ValueError("Import settings must be a JSON object")
    try: json.dumps(parsed,allow_nan=False)
    except ValueError as exc: raise ValueError("Import settings and nested metadata must use finite JSON numbers; NaN/Infinity are not valid measurements.") from exc
    return parsed


def _preview_payload(event:EngineeringEvent)->tuple[dict,str|None]:
    payload=event.model_dump(mode="json",exclude={"signals","states","logs"})
    payload["signals"]=[]
    trimmed=False
    for signal in event.signals:
        count=len(signal.values)
        step=1 if count<=1000 else (count+998)//999
        indices=list(range(0,count,step))
        if indices[-1]!=count-1: indices.append(count-1)
        row=signal.model_dump(mode="json",exclude={"timestamps_s","values"})
        row.update(timestamps_s=[signal.timestamps_s[index] for index in indices],values=[signal.values[index] for index in indices])
        row["metadata"]["preview_total_samples"]=count
        payload["signals"].append(row)
        trimmed=trimmed or len(indices)<count
    payload["states"]=[state.model_dump(mode="json") for state in event.states[:1000]]
    payload["logs"]=[log.model_dump(mode="json") for log in event.logs[:1000]]
    trimmed=trimmed or len(event.states)>1000 or len(event.logs)>1000
    notice="Preview shows at most 1,000 observed samples per channel and the first 1,000 state/text records. Every row was validated; importing preserves the complete accepted capture and original file." if trimmed else None
    return payload,notice


def _prepare_upload(filename:str,contents:bytes,settings:dict):
    """Review original bytes and create an explicitly requested derived copy only."""
    from frib_ds.ingestion.quality import assess_upload,repair_upload
    from frib_ds.quality import validate_expectations
    expectations=validate_expectations(settings.get("quality_expectations"))
    original_quality=assess_upload(filename,contents,settings)
    original_quality["location_basis"]="original_source_rows"
    repairs=settings.get("_repairs",[])
    if not isinstance(repairs,list): raise ValueError("'_repairs' must be a list of selected repair operations.")
    effective,receipt=repair_upload(filename,contents,settings,repairs) if repairs else (contents,None)
    quality=assess_upload(filename,effective,settings) if repairs else original_quality
    if repairs: quality["location_basis"]="reviewed_copy_rows"
    return effective,receipt,{"l1":quality,"original_l1":original_quality,"l2":None},expectations


def _blocking_quality_message(report:dict)->str:
    messages=[]
    for issue in report["issues"]:
        if issue["severity"]!="error": continue
        locations=[]
        if issue.get("column"): locations.append(f"column '{issue['column']}'")
        if issue.get("rows"): locations.append("source rows " + ", ".join(map(str,issue["rows"])))
        messages.append(("CSV " + ", ".join(locations) + ": " if locations else "") + issue["message"])
    return "; ".join(messages)


def _build_reviewed_event(filename:str,contents:bytes,effective:bytes,settings:dict,receipt:dict|None,quality:dict,expectations:dict):
    from frib_ds.ingestion import build_event
    from frib_ds.quality import assess_event
    event=build_event(filename,effective,settings)
    # The provenance checksum always identifies the actual original upload.
    event.provenance.checksum=hashlib.sha256(contents).hexdigest()
    event.metadata["quality_expectations"]=expectations
    event.metadata["upload_quality"]=quality["original_l1"]
    event.metadata["effective_upload_quality"]=quality["l1"]
    if receipt:
        event.metadata["repair_receipt"]=receipt
        event.provenance.notes="Original upload is preserved byte-for-byte. Measurements are a derived view with explicitly selected repairs recorded in metadata.repair_receipt; missing observations were not reconstructed."
    normalized=normalize_event_units(event)
    quality["l2"]=assess_event(normalized,expectations)
    normalized.metadata["data_quality"]=quality["l2"]
    return event,normalized


@app.post("/ingestion/quality")
async def inspect_ingestion_quality(file:UploadFile=File(...),options:str=Form("{}")):
    try:
        contents=await file.read(MAX_DOCUMENT_BYTES+1)
        if len(contents)>MAX_DOCUMENT_BYTES: raise HTTPException(413,"File exceeds the 20 MB import limit")
        _,receipt,quality,_=await run_in_threadpool(_prepare_upload,file.filename or "",contents,_import_options(options))
        result=dict(quality["l1"])
        if receipt: result.update(original_l1=quality["original_l1"],repair_receipt=receipt)
        return result
    except (ValueError,UnicodeError) as exc: raise HTTPException(400,str(exc))
    finally: await file.close()


@app.post("/ingestion/preview")
async def preview_ingestion(file:UploadFile=File(...),options:str=Form("{}"),validate_contents:bool=Form(False,alias="validate")):
    from frib_ds.ingestion import inspect_upload
    try:
        contents=await file.read(MAX_DOCUMENT_BYTES+1)
        if len(contents)>MAX_DOCUMENT_BYTES: raise HTTPException(413,"File exceeds the 20 MB import limit")
        settings=_import_options(options)
        filename=file.filename or ""
        effective,receipt,quality,expectations=await run_in_threadpool(_prepare_upload,filename,contents,settings)
        try: preview=await run_in_threadpool(inspect_upload,filename,effective)
        except ValueError as exc:
            # A damaged file still receives actionable findings and repair choices.
            preview={"filename":filename,"format":filename.rsplit(".",1)[-1].lower(),"columns":[],"validation":{"valid":False,"errors":[str(exc)]}}
        preview.update(quality=quality,repair_receipt=receipt)
        if validate_contents:
            try:
                if quality["l1"]["status"]=="blocked":
                    raise ValueError(_blocking_quality_message(quality["l1"]))
                _,event=await run_in_threadpool(_build_reviewed_event,filename,contents,effective,settings,receipt,quality,expectations)
                payload,notice=await run_in_threadpool(_preview_payload,event)
                preview.update(event=payload,summary=event.metadata.get("import_summary",{}),validation={"valid":True,"errors":[]},preview_notice=notice)
            except ValueError as exc:
                preview["validation"]={"valid":False,"errors":[str(exc)]}
        return preview
    except ValueError as exc: raise HTTPException(400,str(exc))
    finally: await file.close()


@app.post("/ingestion/import")
async def import_evidence(file:UploadFile=File(...),options:str=Form("{}")):
    try:
        contents=await file.read(MAX_DOCUMENT_BYTES+1)
        if len(contents)>MAX_DOCUMENT_BYTES: raise HTTPException(413,"File exceeds the 20 MB import limit")
        settings=_import_options(options)
        effective,receipt,quality,expectations=await run_in_threadpool(_prepare_upload,file.filename or "",contents,settings)
        if quality["l1"]["status"]=="blocked":
            raise ValueError(_blocking_quality_message(quality["l1"]))
        event,_=await run_in_threadpool(_build_reviewed_event,file.filename or "",contents,effective,settings,receipt,quality,expectations)
        services=get_services()
        # Validate and convert the entire file before writing any event records.
        event=await run_in_threadpool(_store_event,services,event)
        try:
            original=await run_in_threadpool(services.files.save_attachment,event.event_id,file.filename,contents)
            services.repo.save_event_file(original)
            derived=None
            if receipt:
                derived_name="reviewed_copy.tsv" if (file.filename or "").lower().endswith(".tsv") else "reviewed_copy.csv"
                derived=await run_in_threadpool(services.files.save_attachment,event.event_id,derived_name,effective)
                services.repo.save_event_file(derived)
        except Exception:
            services.files.delete(event.event_id)
            services.repo.delete_event(event.event_id)
            raise
        services.repo.record_audit("import","event",event.event_id,{"filename":file.filename,"original_sha256":original["checksum"],"unit_policy":"SI_known_preserve_unknown","repair_receipt":receipt,"quality_status":quality["l1"]["status"]})
        quality["l2"]=event.metadata["data_quality"]
        return {"event":event,"summary":event.metadata.get("import_summary",{}),"original_file":original,"derived_file":derived,"quality":quality,"repair_receipt":receipt}
    except (ValueError,UnicodeError) as exc: raise HTTPException(400,str(exc))
    finally: await file.close()


@app.post("/events/generate")
def generate(req:GenerateEventRequest):
    s=get_services()
    try: event=s.generators.for_domain(req.domain).generate(req.seed)
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))
    return _store_event(s,event)


@app.post("/events/generate-custom")
def generate_custom(req:GenerateCustomEventRequest):
    s=get_services()
    try: event=s.generators.get(req.generator).generate(req.seed,req.overrides)
    except (KeyError,ValueError,TypeError) as exc: raise HTTPException(400,str(exc))
    if req.dataset_name: event.metadata["dataset_name"]=req.dataset_name.strip()
    event.metadata["generator_overrides"]=req.overrides
    for key,value in getattr(req,"metadata",{}).items():
        if key in {"cavity","cryomodule","operating_mode","beam_state","configuration"}:
            event.metadata[key]=value
    return _store_event(s,event)


@app.post("/events")
def ingest(event:EngineeringEvent):
    stored=_store_event(get_services(),event)
    return {"event_id":event.event_id,"stored":True,"unit_normalization":stored.metadata.get("unit_normalization",{})}


@app.get("/events")
def list_events(limit:int=Query(100,ge=1,le=1000)):
    return get_services().repo.list_events(limit)


@app.delete("/events/{event_id}")
def delete_event(event_id:str):
    s=get_services()
    if not s.repo.get_event(event_id): raise HTTPException(404,"event not found")
    try: s.files.delete(event_id)
    except ValueError as exc: raise HTTPException(400,str(exc))
    s.repo.delete_event(event_id)
    s.repo.record_audit("delete","event",event_id,{"derived_records_removed":True})
    return {"event_id":event_id,"deleted":True}


@app.get("/events/{event_id}")
def get_event(event_id:str):
    event=get_services().repo.get_event(event_id)
    if not event: raise HTTPException(404,"event not found")
    # Older stored captures may predate SI ingestion; views use the same units as
    # quality thresholds without changing the historical record or its bytes.
    return normalize_event_units(event)


@app.get("/events/{event_id}/download")
def download_event(event_id:str,format:Literal["json","csv","normalized-json"]="json"):
    s=get_services(); event=s.repo.get_event(event_id)
    if not event: raise HTTPException(404,"event not found")
    if format=="normalized-json":
        normalized=normalize_event_units(event)
        return Response(normalized.model_dump_json(indent=2),media_type="application/json",headers={"Content-Disposition":f'attachment; filename="{event_id}_normalized.json"'})
    if format=="json":
        try: original=s.files.original(event_id)
        except ValueError as exc: raise HTTPException(400,str(exc))
        if original.is_file(): return FileResponse(original,media_type="application/json",filename=f"{event_id}.json")
        # Support evidence imported into databases by older versions.
        return Response(event.model_dump_json(indent=2),media_type="application/json",headers={"Content-Disposition":f'attachment; filename="{event_id}.json"'})
    event=normalize_event_units(event)
    output=io.StringIO(newline="")
    writer=csv.writer(output)
    writer.writerow(["kind","name","timestamp_s","value","unit","level","source","message"])
    for signal in event.signals:
        for timestamp,value in zip(signal.timestamps_s,signal.values): writer.writerow(["signal",signal.name,timestamp,value,signal.unit,"","",""])
    for state in event.states: writer.writerow(["state",state.name,state.timestamp_s,state.value,"","","",""])
    for log in event.logs: writer.writerow(["log","",log.timestamp_s,"","",log.level,log.source,log.message])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{event_id}.csv"'})


@app.post("/events/{event_id}/analyze")
def analyze(event_id:str,req:QualityReviewRequest|None=None):
    s=get_services(); event=s.repo.get_event(event_id)
    if not event: raise HTTPException(404,"event not found")
    try: analysis=s.processors.analyze(normalize_event_units(event),req.expectations if req else None)
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))
    s.repo.save_analysis(analysis)
    s.repo.record_audit("analyze","event",event_id,{"processor":analysis.processor,"processor_version":analysis.processor_version})
    return analysis


@app.post("/events/{event_id}/quality")
def review_event_quality(event_id:str,req:QualityReviewRequest):
    from frib_ds.quality import assess_event
    event=get_services().repo.get_event(event_id)
    if not event: raise HTTPException(404,"event not found")
    try: return assess_event(normalize_event_units(event),req.expectations if req.expectations is not None else event.metadata.get("quality_expectations"))
    except ValueError as exc: raise HTTPException(400,str(exc))


@app.post("/events/{event_id}/files")
async def upload_event_file(event_id:str,file:UploadFile=File(...)):
    s=get_services()
    if not s.repo.get_event(event_id): raise HTTPException(404,"event not found")
    try:
        contents=await file.read(MAX_DOCUMENT_BYTES+1)
        if len(contents)>MAX_DOCUMENT_BYTES: raise HTTPException(413,"Evidence file exceeds the 20 MB upload limit")
        metadata=s.files.save_attachment(event_id,file.filename or "",contents)
        try: s.repo.save_event_file(metadata)
        except Exception:
            s.files.delete_attachment(event_id,metadata["file_id"])
            raise
        s.repo.record_audit("upload","event_file",metadata["file_id"],{"event_id":event_id,"filename":metadata["filename"],"checksum":metadata["checksum"]})
        return metadata
    except ValueError as exc: raise HTTPException(400,str(exc))
    finally: await file.close()


@app.get("/events/{event_id}/files")
def list_event_files(event_id:str):
    s=get_services()
    if not s.repo.get_event(event_id): raise HTTPException(404,"event not found")
    return s.repo.list_event_files(event_id)


@app.get("/events/{event_id}/files/{file_id}/download")
def download_event_file(event_id:str,file_id:str):
    s=get_services(); metadata=s.repo.get_event_file(event_id,file_id)
    if not metadata: raise HTTPException(404,"evidence file not found")
    try: path=s.files.attachment_path(event_id,file_id)
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not path.is_file(): raise HTTPException(404,"stored original evidence file is unavailable")
    return FileResponse(path,media_type=mimetypes.guess_type(metadata["filename"])[0] or "application/octet-stream",filename=metadata["filename"])


@app.delete("/events/{event_id}/files/{file_id}")
def delete_event_file(event_id:str,file_id:str):
    s=get_services(); metadata=s.repo.get_event_file(event_id,file_id)
    if not metadata: raise HTTPException(404,"evidence file not found")
    try: s.files.delete_attachment(event_id,file_id)
    except ValueError as exc: raise HTTPException(400,str(exc))
    s.repo.delete_event_file(event_id,file_id)
    s.repo.record_audit("delete","event_file",file_id,{"event_id":event_id,"filename":metadata["filename"],"checksum":metadata["checksum"]})
    return {"event_id":event_id,"file_id":file_id,"deleted":True}


@app.get("/events/{event_id}/analysis")
def get_analysis(event_id:str):
    analysis=get_services().repo.get_analysis(event_id)
    if not analysis: raise HTTPException(404,"analysis not found")
    return analysis


@app.post("/documents/index")
async def index_document(file:UploadFile=File(...),approved:bool=Form(False),title:str|None=Form(None),version:str|None=Form(None)):
    try:
        DocumentStore.validate_filename(file.filename or "")
        contents=await file.read(MAX_DOCUMENT_BYTES+1)
        if len(contents)>MAX_DOCUMENT_BYTES: raise HTTPException(413,"Document exceeds the 20 MB upload limit")
        return await run_in_threadpool(get_services().documents.upload,file.filename,contents,approved,title,version)
    except (ValueError,UnicodeError) as exc: raise HTTPException(400,str(exc))
    except RuntimeError as exc: raise HTTPException(400,str(exc))
    finally: await file.close()


@app.get("/documents")
def list_documents(limit:int=Query(1000,ge=1,le=1000)):
    return get_services().repo.list_documents(limit)


@app.get("/documents/{document_id}/download")
def download_document(document_id:str):
    try: original,metadata=get_services().documents.original(document_id)
    except KeyError: raise HTTPException(404,"document not found")
    except FileNotFoundError as exc: raise HTTPException(404,str(exc))
    except ValueError as exc: raise HTTPException(400,str(exc))
    media_type="application/pdf" if original.suffix==".pdf" else "text/plain"
    return FileResponse(original,media_type=media_type,filename=metadata["filename"])


@app.delete("/documents/{document_id}")
def delete_document(document_id:str):
    try: get_services().documents.delete(document_id)
    except KeyError: raise HTTPException(404,"document not found")
    except ValueError as exc: raise HTTPException(400,str(exc))
    return {"document_id":document_id,"deleted":True}


@app.post("/rag/query")
def rag_query(req:RAGQueryRequest):
    s=get_services(); event=s.repo.get_event(req.event_id) if req.event_id else None
    if req.event_id and not event: raise HTTPException(404,"event not found")
    analysis=s.repo.get_analysis(req.event_id) if req.event_id else None
    return s.rag.query(req.question,event,analysis)


@app.post("/events/{event_id}/draft")
def draft(event_id:str,question:str="What approved procedural context is relevant to this event?"):
    s=get_services(); event=s.repo.get_event(event_id); analysis=s.repo.get_analysis(event_id)
    if not event: raise HTTPException(404,"event not found")
    if not analysis: raise HTTPException(400,"analyze the event before creating a draft")
    result=s.knowledge.create_draft(event,analysis,s.rag.query(question,event,analysis))
    s.repo.record_audit("create","draft",result.draft_id,{"event_id":event_id})
    return result


@app.get("/events/{event_id}/draft")
def latest_draft(event_id:str):
    result=get_services().repo.latest_draft_for_event(event_id)
    if not result: raise HTTPException(404,"draft not found")
    return result


@app.get("/drafts/{draft_id}")
def get_draft(draft_id:str):
    result=get_services().repo.get_draft(draft_id)
    if not result: raise HTTPException(404,"draft not found")
    return result


@app.post("/drafts/{draft_id}/review")
def review(draft_id:str,req:ReviewRequest):
    s=get_services(); result=s.repo.get_draft(draft_id)
    if not result: raise HTTPException(404,"draft not found")
    try: record,knowledge=s.knowledge.review(result,req)
    except ValueError as exc: raise HTTPException(400,str(exc))
    return {"review":record,"knowledge":knowledge}


@app.get("/knowledge")
def knowledge(limit:int=Query(100,ge=1,le=1000)):
    return get_services().repo.list_knowledge(limit)


@app.get("/knowledge/search")
def search_knowledge(q:str,limit:int=Query(25,ge=1,le=1000)):
    return get_services().repo.search_knowledge(q,limit)


@app.get("/audit")
def audit(limit:int=Query(100,ge=1,le=1000)):
    return get_services().repo.list_audit(limit)
