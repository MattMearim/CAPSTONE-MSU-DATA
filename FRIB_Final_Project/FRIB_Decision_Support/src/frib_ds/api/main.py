from __future__ import annotations

import csv
import os
import io
import sqlite3
import mimetypes
import json
import hashlib
import asyncio
import requests
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, Response
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from frib_ds.bootstrap import get_services
from frib_ds.knowledge.service import KnowledgeGenerationUnavailable
from frib_ds.models import EngineeringEvent, GenerateEventRequest, GenerateCustomEventRequest, RAGQueryRequest, ReviewRequest, UnitConversionRequest, QualityReviewRequest, ResetDataRequest
from frib_ds.storage.documents import MAX_DOCUMENT_BYTES, DocumentStore
from frib_ds.storage.reset import DataLifecycleLock,UnsafeResetPath
from frib_ds.config import get_config
from frib_ds.units import unit_catalog, normalize_unit, convert_value, normalize_event_units
from frib_ds.system_manager import get_system_manager
from frib_ds.api.security import LocalRequestSecurityMiddleware
from frib_ds.connections import workspace_connections
from frib_ds.ingestion.bulk import BulkImportError,BulkBusyError,bulk_limits,get_bulk_manager,safe_relative_name,CHUNK_BYTES

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
        pure_system=path in {"/system/info","/system/versions/check","/system/upgrades/plan"} or path.startswith('/system/ai')
        guarded=scope["type"]=="http" and not pure_system and any(path==prefix or path.startswith(prefix+"/") for prefix in ("/events","/documents","/rag","/drafts","/knowledge","/connections","/audit","/system","/ingestion/import"))
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
# Outermost request guard runs before parsing or acquiring the data lock.
app.add_middleware(LocalRequestSecurityMiddleware)


class UpgradePlanRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mode:Literal["required","selected"]="required"
    components:list[str]=Field(default_factory=list,max_length=13)
    upgrade_pip:StrictBool=False
    upgrade_python:StrictBool=False
    include_semantic:StrictBool=False


class VersionCheckRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")


from frib_ds.ai_settings import AISelection, ModelServer, ApplySelection, AutomaticSetup, InstalledModelSwitch, get_ai_manager, list_models, read_profiles, selection_from_models, start_bundled_server
from frib_ds.model_library import NewModelRequest, QualityConfiguration, ModelDeletion, get_model_library
from frib_ds.quality_agent_models import FindingReview, RepairApproval, ValidationExplanationRequest
from frib_ds.quality_agent_settings import read_quality_settings


def _ai_error(exc):
    if isinstance(exc, (ValueError, KeyError)):
        return HTTPException(400, str(exc).strip("'"))
    if isinstance(exc, requests.RequestException):
        return HTTPException(503, 'The local model server could not complete the request. Check its address, loaded model and server logs.')
    return HTTPException(503, str(exc)[:500])


@app.get('/system/ai')
def ai_settings_info():
    services = get_services()
    manager = get_ai_manager(services.config.config_dir)
    try:
        active = selection_from_models(services.config.models)
        profiles = read_profiles(services.config.config_dir)
        return {'active': active.model_dump(), **profiles,
                'embeddings': services.config.models.get('embeddings', {}),
                'download_available': manager.can_download(active),
                'managed_ollama_url': os.getenv('FRIB_MANAGED_OLLAMA_URL'),
                'bundled_ollama_available': bool(os.getenv('FRIB_DEPENDENCIES_DIR')),
                'model_storage': os.getenv('OLLAMA_MODELS'),
                'setup': manager.setup_status(),
                'apply_mode': 'live'}
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/models')
def ai_models(server: ModelServer):
    try:
        return {'models': list_models(server), 'download_available': get_ai_manager(get_config().config_dir).can_download(server)}
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.get('/system/ai/models')
def ai_models_read(provider: str, base_url: str):
    try:
        return ai_models(ModelServer(provider=provider, base_url=base_url))
    except HTTPException:
        raise
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/start-ollama')
def ai_start_bundled():
    try:
        return start_bundled_server()
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/test')
def ai_test(selection: AISelection):
    try:
        return get_ai_manager(get_config().config_dir).test(selection)
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.get('/system/ai/resources')
def ai_resources(storage: bool = True):
    from frib_ds.ai_resources import resource_snapshot
    return resource_snapshot(get_services(), include_storage=storage)


_MONITOR_ASSETS = Path(__file__).resolve().parents[1] / 'dashboard' / 'resource_monitor'
_MONITOR_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'self'; base-uri 'none'; object-src 'none'; form-action 'none'; "
                "frame-ancestors 'self' http://localhost:* http://127.0.0.1:* http://[::1]:*")


@app.get('/system/ai/monitor', include_in_schema=False)
def live_resource_monitor():
    return FileResponse(_MONITOR_ASSETS / 'index.html', media_type='text/html',
                        headers={'Content-Security-Policy': _MONITOR_CSP})


@app.get('/system/ai/monitor/{asset}', include_in_schema=False)
def live_resource_monitor_asset(asset: Literal['monitor.css', 'monitor.js']):
    return FileResponse(_MONITOR_ASSETS / asset, media_type='text/css' if asset.endswith('.css') else 'text/javascript',
                        headers={'Content-Security-Policy': _MONITOR_CSP})


@app.post('/system/ai/switch', status_code=202)
def ai_switch_installed(request: InstalledModelSwitch):
    try:
        return get_ai_manager(get_config().config_dir).begin_switch(request, get_services())
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.get('/system/ai/recommendations')
def ai_recommendations(mode: str = 'balanced', refresh: bool = False):
    try:
        return get_ai_manager(get_config().config_dir).recommendations(mode, refresh)
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.get('/system/ai/library')
def model_library(provider: str='ollama',base_url: str='http://127.0.0.1:11434'):
    try:
        services=get_services()
        return get_model_library(get_ai_manager(services.config.config_dir)).inventory(services,ModelServer(provider=provider,base_url=base_url))
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/library/install',status_code=202)
def install_new_model(request:NewModelRequest):
    try:
        services=get_services()
        return get_model_library(get_ai_manager(services.config.config_dir)).install(request,services)
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/library/delete-preview')
def preview_model_deletion(request:ModelDeletion):
    try:
        services=get_services()
        return get_model_library(get_ai_manager(services.config.config_dir)).deletion_plan(request,services)
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/library/delete')
def delete_unused_model(request:ModelDeletion):
    try:
        services=get_services()
        return get_model_library(get_ai_manager(services.config.config_dir)).delete(request,services)
    except Exception as exc: raise _ai_error(exc) from exc


@app.get('/system/ai/quality-agent')
def quality_agent_settings():
    services=get_services()
    try:
        return {'settings':read_quality_settings(services.config.config_dir).model_dump(mode='json'),
                'jobs':services.repo.quality_job_counts(),'current_run':services.quality_agent.current_run,
                'last_error':services.quality_agent.last_error}
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/quality-agent/test')
def test_quality_agent(selection:AISelection):
    try: return get_model_library(get_ai_manager(get_config().config_dir)).test_quality(selection)
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/quality-agent/configure')
def configure_quality_agent(request:QualityConfiguration):
    try:
        services=get_services()
        return get_model_library(get_ai_manager(services.config.config_dir)).configure_quality(request,services)
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/system/ai/quality-agent/scan-existing',status_code=202)
def quality_agent_scan_existing():
    services=get_services()
    try:
        queued=[services.quality_agent.schedule(row['event_id'],reason='user requested existing-dataset scan') for row in services.repo.list_events(limit=1000)]
        return {'scheduled':sum(item.get('status')=='queued' for item in queued),'datasets_considered':len(queued),'limit':1000}
    except Exception as exc: raise _ai_error(exc) from exc


@app.get('/system/ai/setup')
def ai_setup_status():
    return get_ai_manager(get_config().config_dir).setup_status()


@app.post('/system/ai/setup', status_code=202)
def ai_automatic_setup(request: AutomaticSetup):
    try:
        return get_ai_manager(get_config().config_dir).begin_setup(request, get_services())
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/setup/cancel')
def ai_cancel_setup():
    try:
        return get_ai_manager(get_config().config_dir).cancel_setup()
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/automation/pause')
def ai_pause_automation():
    try:
        return get_ai_manager(get_config().config_dir).pause_automation()
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/apply')
def ai_apply(selection: ApplySelection):
    try:
        return get_ai_manager(get_config().config_dir).apply(selection, get_services())
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.post('/system/ai/downloads', status_code=202)
def ai_download(selection: AISelection):
    try:
        return get_ai_manager(get_config().config_dir).download(selection)
    except Exception as exc:
        raise _ai_error(exc) from exc


@app.get('/system/ai/downloads/{job_id}')
def ai_download_status(job_id: str):
    try:
        return get_ai_manager(get_config().config_dir).download_status(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc


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
    try:
        if hasattr(s,'quality_agent'): s.quality_agent.schedule(normalized.event_id,reason='incoming data',lock_held=True)
    except Exception as exc:
        # The evidence is safely committed even if an optional agent is offline.
        s.repo.record_audit('quality_agent_schedule_failed','event',event.event_id,{'error':str(exc)[:300]})
    return normalized


@app.get("/health")
def health():
    s=get_services()
    return {"status":"ok","instance_id":os.getenv("FRIB_INSTANCE_ID"),"llm_provider":s.config.models.get("llm",{}).get("provider"),"llm_model":s.config.models.get("llm",{}).get("model"),"embedding_provider":s.config.models.get("embeddings",{}).get("provider"),"vector_provider":s.config.models.get("vector_store",{}).get("provider"),"domains":s.processors.domains()}


@app.get("/connections")
def connections(limit:int=Query(60,ge=1,le=100)):
    """Read saved workspace relationships without AI generation or mutations."""
    return workspace_connections(get_services().repo,limit)


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


def _bulk_import_file(path,name,kind,settings,approved_documents):
    """Use the ordinary validated import path without AI analysis/generation."""
    contents=path.read_bytes()
    filename=PurePosixPath(name).name
    services=get_services()
    try:
        if kind=="document":
            metadata=services.documents.upload(filename,contents,approved=approved_documents)
            # This worker already updated its own vector index under the data
            # lifecycle lock; polling must not re-embed/rehydrate the catalog.
            services.documents_generation=services.repo.metadata("documents_generation")
            return {"document_id":metadata["document_id"],"approved":metadata["approved"]}
        effective=contents; receipt=None; quality=None
        if filename.lower().endswith(".json"):
            try: event=EngineeringEvent.model_validate_json(contents)
            except ValueError as exc: raise ValueError("JSON datasets must follow the FRIB EngineeringEvent format. Import CSV/TSV for tabular data, or correct the JSON fields before retrying.") from exc
        else:
            effective,receipt,quality,expectations=_prepare_upload(filename,contents,settings)
            if quality["l1"]["status"]=="blocked":
                raise ValueError(_blocking_quality_message(quality["l1"]))
            event,_=_build_reviewed_event(filename,contents,effective,settings,receipt,quality,expectations)
        event.metadata["bulk_source_path"]=name
        event=_store_event(services,event)
        try:
            original=services.files.save_attachment(event.event_id,filename,contents)
            services.repo.save_event_file(original)
            if receipt:
                derived_name="reviewed_copy.tsv" if filename.lower().endswith(".tsv") else "reviewed_copy.csv"
                derived=services.files.save_attachment(event.event_id,derived_name,effective)
                services.repo.save_event_file(derived)
        except Exception:
            services.files.delete(event.event_id)
            services.repo.delete_event(event.event_id)
            raise
        services.repo.record_audit("import","event",event.event_id,{"filename":filename,"bulk_source_path":name,"original_sha256":original["checksum"],"unit_policy":"SI_known_preserve_unknown","repair_receipt":receipt})
        result={"event_id":event.event_id,"signal_count":len(event.signals),"state_count":len(event.states),"log_count":len(event.logs),
                "quality_status":event.metadata.get("data_quality",{}).get("status","unknown")}
        if quality:
            result["warnings"]=[issue["message"][:300] for issue in quality["l1"].get("issues",[]) if issue["severity"]=="warning"][:10]
        return result
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def _bulk_options(options):
    settings=_import_options(options)
    allowed={"domain","time_column","time_unit","column_roles","signal_names","source_units","target_units","unit_columns","invalid_rows","metadata","imported_by","quality_expectations","_repairs"}
    if set(settings)-allowed:
        raise ValueError("Bulk settings support domain, time/column mappings, units, metadata, quality expectations and explicitly selected repairs. Shared event_id or dataset_name values are not allowed; each file keeps its own identity.")
    return settings


@app.get("/ingestion/bulk/limits")
def ingestion_bulk_limits():
    return {**bulk_limits(),"supported_datasets":["csv","tsv","json","log"],"supported_documents":["pdf","txt","md"],"archives":["zip"],"documents_approved_by_default":False,"max_active_jobs":2}


@app.post("/ingestion/bulk",status_code=202)
async def import_bulk(files:list[UploadFile]=File(...),options:str=Form("{}"),approved_documents:bool=Form(False)):
    manager=None; job=None; submitted=False
    try:
        settings=_bulk_options(options)
        limits=bulk_limits()
        if len(files)>limits["max_files"]:
            raise BulkImportError("Too many uploaded files for one batch.")
        services=get_services()
        manager=get_bulk_manager(str(get_config().data_dir))
        job=manager.begin()
        for upload in files:
            name=safe_relative_name(upload.filename or "")
            path=manager.staged_path(job["job_id"])
            file_size=0
            archive=name.lower().endswith(".zip")
            with path.open("xb") as stream:
                while chunk:=await upload.read(CHUNK_BYTES):
                    if manager.is_cancelled(job["job_id"]):
                        raise BulkImportError("Project data was reset or this upload was cancelled. Start a new batch when ready.")
                    job["uploaded_bytes"]+=len(chunk)
                    file_size+=len(chunk)
                    if job["uploaded_bytes"]>limits["max_total_bytes"]:
                        raise BulkImportError("Uploaded files exceed the batch size limit. Split this folder into smaller batches.")
                    # Oversized ordinary files receive their own failure row;
                    # do not waste disk staging their excess bytes.
                    if archive: stream.write(chunk)
                    else:
                        remaining=limits["max_file_bytes"]+1-stream.tell()
                        if remaining>0: stream.write(chunk[:remaining])
            await run_in_threadpool(manager.add_file,job["job_id"],name,path,file_size)
            await upload.close()
        # Capture reset generation under the same lock as the worker commits.
        # Uploading and ZIP checks do not block other workspace pages.
        lock=DataLifecycleLock(get_config().data_dir)
        try:
            while not lock.try_acquire(): await asyncio.sleep(0.01)
            if manager.is_cancelled(job["job_id"]):
                raise BulkImportError("Project data was reset or this upload was cancelled. Start a new batch when ready.")
            if not await run_in_threadpool(services.refresh_data_state):
                raise HTTPException(503,"Project data reset is incomplete. Finish the reset before importing files.")
            generation=(services.repo.metadata("reset_generation"),False)
        finally: lock.close()
        result=manager.submit(job["job_id"],_bulk_import_file,settings,approved_documents,generation,lambda:(services.repo.metadata("reset_generation"),bool(services.repo.pending_reset())))
        submitted=True
        return result
    except BulkBusyError as exc: raise HTTPException(429,str(exc))
    except (BulkImportError,ValueError,UnicodeError) as exc: raise HTTPException(400,str(exc))
    except OSError as exc: raise HTTPException(507,"There is not enough available local storage or permission to stage this import. Free disk space and retry a smaller batch.") from exc
    finally:
        if manager and job and not submitted: await run_in_threadpool(manager.abort,job["job_id"])
        for upload in files: await upload.close()


@app.get("/ingestion/bulk/{job_id}")
def ingestion_bulk_status(job_id:str):
    try: return get_bulk_manager(str(get_config().data_dir)).status(job_id)
    except KeyError as exc: raise HTTPException(404,"Bulk import not found") from exc
    except (BulkImportError,ValueError) as exc: raise HTTPException(409,"Bulk import report is unavailable or unsafe.") from exc


@app.post("/ingestion/bulk/{job_id}/cancel")
def cancel_bulk_import(job_id:str):
    try: return get_bulk_manager(str(get_config().data_dir)).cancel(job_id)
    except KeyError as exc: raise HTTPException(404,"Bulk import not found") from exc
    except (BulkImportError,ValueError) as exc: raise HTTPException(409,"Bulk import report is unavailable or unsafe.") from exc


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


@app.get('/events/{event_id}/quality-agent')
def event_quality_agent(event_id:str):
    services=get_services()
    if not services.repo.get_event(event_id): raise HTTPException(404,'Dataset not found.')
    return services.quality_agent.event_status(event_id)


@app.post('/events/{event_id}/quality-agent',status_code=202)
def run_event_quality_agent(event_id:str):
    try: return get_services().quality_agent.schedule(event_id,reason='user requested graph review',force=True,lock_held=True)
    except KeyError as exc: raise HTTPException(404,str(exc)) from exc
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc


@app.post('/quality-agent/runs/{run_id}/findings/{finding_id}/review')
def review_quality_finding(run_id:str,finding_id:str,request:FindingReview):
    try: return get_services().quality_agent.review(run_id,finding_id,request)
    except KeyError as exc: raise HTTPException(404,str(exc)) from exc
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc


@app.post('/quality-agent/explain-validation')
def explain_validation_with_agent(request:ValidationExplanationRequest):
    try: return get_services().quality_agent.explain_validation(request)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    except Exception as exc: raise _ai_error(exc) from exc


@app.post('/quality-agent/runs/{run_id}/findings/{finding_id}/repair')
def apply_quality_repair(run_id:str,finding_id:str,request:RepairApproval):
    try: return get_services().quality_agent.apply_repair(run_id,finding_id,request)
    except KeyError as exc: raise HTTPException(404,str(exc)) from exc
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc


def _spreadsheet_cell(value):
    """Keep source text literal when a standardized CSV is opened in a sheet."""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


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
        for timestamp,value in zip(signal.timestamps_s,signal.values): writer.writerow([_spreadsheet_cell(cell) for cell in ["signal",signal.name,timestamp,value,signal.unit,"","",""]])
    for state in event.states: writer.writerow([_spreadsheet_cell(cell) for cell in ["state",state.name,state.timestamp_s,state.value,"","","",""]])
    for log in event.logs: writer.writerow([_spreadsheet_cell(cell) for cell in ["log","",log.timestamp_s,"","",log.level,log.source,log.message]])
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
    try:
        result=s.knowledge.create_draft(event,analysis,s.rag.query(question,event,analysis))
    except KnowledgeGenerationUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc
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
