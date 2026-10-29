"""Integration contracts for mixed evidence and deterministic unit conversion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frib_ds.api import main as api
from frib_ds.bootstrap import Services, get_services
from frib_ds.config import get_config


MIXED_CSV=(
    b"time_ms,voltage [mV],temperature [C],mode,enabled,note\r\n"
    b"0,1000,20,RUNNING,true,[INFO] Beam enabled\r\n"
    b"100,2 kV,21,WARNING,false,[WARNING] Pressure trend noted\r\n"
    b"200,500 mV,22,INTERLOCKED,true,[ERROR] Interlock reported\r\n"
)
MIXED_OPTIONS={"event_id":"MIXED-API-1","domain":"rf","dataset_name":"Imported mixed evidence",
    "time_column":"time_ms","time_unit":"ms",
    "column_roles":{"voltage [mV]":"numeric","temperature [C]":"numeric","mode":"category","enabled":"category","note":"log"},
    "signal_names":{"voltage [mV]":"voltage","temperature [C]":"temperature","mode":"operating_mode"}}


@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setenv("FRIB_DATA_DIR",str(tmp_path/"data"))
    monkeypatch.setenv("FRIB_CONFIG_DIR",str(Path("config").resolve()))
    monkeypatch.setenv("FRIB_LLM_PROVIDER","mock")
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER","hash")
    monkeypatch.setenv("FRIB_VECTOR_PROVIDER","sqlite")
    get_config.cache_clear(); get_services.cache_clear()
    state={"services":Services()}
    monkeypatch.setattr(api,"get_services",lambda:state["services"])
    try:
        with TestClient(api.app) as client: yield client,state,tmp_path
    finally:
        get_config.cache_clear(); get_services.cache_clear()


def upload(client,path="/ingestion/import",filename="mixed.csv",contents=MIXED_CSV,options=None,validate=False):
    data={"options":json.dumps(MIXED_OPTIONS if options is None else options)}
    if validate: data["validate"]="true"
    return client.post(path,files={"file":(filename,contents,"application/octet-stream")},data=data)


def assert_no_capture_writes(client,tmp_path):
    assert client.get("/events").json()==[]
    assert list((tmp_path/"data"/"events").iterdir())==[]
    assert client.get("/knowledge").json()==[]
    assert client.get("/audit").json()==[]


def test_unit_catalog_and_offset_conversion(environment):
    client,_,_=environment
    catalog=client.get("/units")
    assert catalog.status_code==200
    by_symbol={item["symbol"]:item for item in catalog.json()}
    assert by_symbol["mV"]["dimension"]==by_symbol["MV"]["dimension"]=="voltage"
    assert by_symbol["mV"]["scale"]!=by_symbol["MV"]["scale"]
    assert by_symbol["C"]["canonical_unit"]=="K"
    converted=client.post("/units/convert",json={"value":32,"from_unit":"°F","to_unit":"C"})
    assert converted.status_code==200,converted.text
    assert converted.json()["converted_value"]==pytest.approx(0)
    assert converted.json()["dimension"]=="temperature"
    assert converted.json()["from_unit"]=="F"


@pytest.mark.parametrize("payload,status",[
    ({"value":1,"from_unit":"V","to_unit":"W"},400),
    ({"value":1,"from_unit":"mv","to_unit":"V"},400),
    ({"value":1,"from_unit":"dBm","to_unit":"W"},400),
    ({"value":True,"from_unit":"V","to_unit":"mV"},422),
    ({"value":"NaN","from_unit":"V","to_unit":"mV"},422),
    ({"value":"1e999","from_unit":"V","to_unit":"mV"},422),
    ({"value":None,"from_unit":"V","to_unit":"mV"},422),
])
def test_converter_rejects_incompatible_unknown_and_non_numeric_values(environment,payload,status):
    client,_,tmp_path=environment
    response=client.post("/units/convert",json=payload)
    assert response.status_code==status,response.text
    assert_no_capture_writes(client,tmp_path)


def test_validated_preview_understands_mixed_units_without_persistence(environment):
    client,_,tmp_path=environment
    response=upload(client,path="/ingestion/preview",validate=True)
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview["format"]=="csv" and preview["row_count"]==3
    assert preview["validation"]=={"valid":True,"errors":[]}
    event=preview["event"]
    signals={signal["name"]:signal for signal in event["signals"]}
    assert signals["voltage"]["unit"]=="V"
    assert signals["voltage"]["values"]==pytest.approx([1,2000,.5])
    assert signals["temperature"]["unit"]=="K"
    assert signals["temperature"]["values"]==pytest.approx([293.15,294.15,295.15])
    assert signals["voltage"]["timestamps_s"]==pytest.approx([0,.1,.2])
    assert {state["value"] for state in event["states"]}>={"RUNNING","WARNING","INTERLOCKED","true","false"}
    assert {log["level"] for log in event["logs"]}=={"INFO","WARNING","ERROR"}
    assert_no_capture_writes(client,tmp_path)


def test_import_preserves_exact_source_and_separates_raw_from_si_exports(environment):
    client,state,_=environment
    response=upload(client)
    assert response.status_code==200,response.text
    imported=response.json(); event=imported["event"]; event_id=event["event_id"]
    assert imported["summary"]["numeric_signals"]==2
    assert imported["summary"]["log_entries"]==3
    assert event["provenance"]["checksum"]==hashlib.sha256(MIXED_CSV).hexdigest()
    original=imported["original_file"]
    assert original["checksum"]==hashlib.sha256(MIXED_CSV).hexdigest()
    assert original["size_bytes"]==len(MIXED_CSV)
    source=client.get(f'/events/{event_id}/files/{original["file_id"]}/download')
    assert source.content==MIXED_CSV
    raw=client.get(f"/events/{event_id}/download?format=json").json()
    normalized=client.get(f"/events/{event_id}/download?format=normalized-json").json()
    raw_voltage=next(signal for signal in raw["signals"] if signal["name"]=="voltage")
    normalized_voltage=next(signal for signal in normalized["signals"] if signal["name"]=="voltage")
    assert raw_voltage["unit"]=="mV" and raw_voltage["values"]==pytest.approx([1000,2e6,500])
    assert normalized_voltage["unit"]=="V" and normalized_voltage["values"]==pytest.approx([1,2000,.5])
    assert normalized_voltage["metadata"]["unit_conversion"]["original_unit"]=="mV"
    assert raw["states"]==normalized["states"] and raw["logs"]==normalized["logs"]
    state["services"]=Services()
    stored=client.get(f"/events/{event_id}").json()
    assert stored==event
    assert client.get(f'/events/{event_id}/files/{original["file_id"]}/download').content==MIXED_CSV


def test_per_row_unit_column_uses_compatible_scales_and_retains_categories(environment):
    client,_,_=environment
    contents=(b"time [ms],gradient,gradient_unit,mode\n"
        b"0,5,MV/m,READY\n10,6000,kV/m,RUN\n20,7000000,V/m,RUN\n")
    options={"event_id":"PER-ROW-UNITS","domain":"rf", "unit_columns":{"gradient":"gradient_unit"},
        "column_roles":{"gradient":"numeric","gradient_unit":"ignore","mode":"category"}}
    response=upload(client,contents=contents,options=options)
    assert response.status_code==200,response.text
    event=response.json()["event"]
    assert len(event["signals"])==1
    gradient=event["signals"][0]
    assert gradient["unit"]=="V/m"
    assert gradient["values"]==pytest.approx([5e6,6e6,7e6])
    assert gradient["timestamps_s"]==pytest.approx([0,.01,.02])
    assert gradient["metadata"]["source_units"]==["MV/m","V/m","kV/m"]
    assert [state["value"] for state in event["states"]]==["READY","RUN"]


@pytest.mark.parametrize("contents,changes,needle",[
    (MIXED_CSV.replace(b"1000,20",b"broken,20"),{},"voltage"),
    (MIXED_CSV,{"target_units":{"voltage [mV]":"W"}},"Incompatible"),
    (MIXED_CSV,{"source_units":{"voltage [mV]":"banana"}},"Unknown unit"),
    (MIXED_CSV.replace(b"100,2 kV",b"0,2 kV"),{},"timestamp"),
])
def test_invalid_numeric_import_is_atomic_and_preview_explains_failure(environment,contents,changes,needle):
    client,_,tmp_path=environment
    options={**MIXED_OPTIONS,**changes}
    preview=upload(client,path="/ingestion/preview",contents=contents,options=options,validate=True)
    assert preview.status_code==200,preview.text
    validation=preview.json()["validation"]
    assert validation["valid"] is False and needle.lower() in " ".join(validation["errors"]).lower()
    response=upload(client,contents=contents,options=options)
    assert response.status_code==400,response.text
    assert needle.lower() in response.text.lower()
    assert_no_capture_writes(client,tmp_path)


@pytest.mark.parametrize("options",["not json","[]","null"])
def test_malformed_import_settings_write_nothing(environment,options):
    client,_,tmp_path=environment
    response=client.post("/ingestion/import",files={"file":("mixed.csv",MIXED_CSV)},data={"options":options})
    assert response.status_code==400,response.text
    assert_no_capture_writes(client,tmp_path)


def test_duplicate_import_preserves_first_capture_and_original(environment):
    client,_,tmp_path=environment
    first=upload(client)
    assert first.status_code==200,first.text
    event=first.json()["event"]; event_id=event["event_id"]
    original=first.json()["original_file"]
    second=upload(client,contents=MIXED_CSV.replace(b"1000,20",b"9999,20"))
    assert second.status_code==409,second.text
    assert len(client.get("/events").json())==1
    assert client.get(f"/events/{event_id}").json()==event
    assert client.get(f"/events/{event_id}/files").json()==[original]
    assert client.get(f'/events/{event_id}/files/{original["file_id"]}/download').content==MIXED_CSV
    assert len(list((tmp_path/"data"/"events").iterdir()))==1


def test_text_only_rf_evidence_has_full_review_lifecycle_and_restart_delete(environment):
    client,state,tmp_path=environment
    narrative=(b"2026-10-10T12:00:00Z [INFO] Beam enabled\n"
        b"2026-10-10T12:00:01Z [WARNING] Pressure change observed\n"
        b"2026-10-10T12:00:02Z [ERROR] Interlock activated\n")
    response=upload(client,filename="operator.log",contents=narrative,options={"event_id":"TEXT-RF-1","domain":"rf","dataset_name":"Recorded operator narrative"})
    assert response.status_code==200,response.text
    event=response.json()["event"]; event_id=event["event_id"]
    assert event["signals"]==[] and len(event["logs"])==3
    assert all(log["message"] in narrative.decode() for log in event["logs"])
    analysis=client.post(f"/events/{event_id}/analyze")
    assert analysis.status_code==200,analysis.text
    result=analysis.json()
    assert result["processor"]=="mixed_evidence_summary"
    assert result["features"]["evidence_summary"]["text_records"]==3
    assert any("required rf" in warning for warning in result["features"]["warnings"])
    draft_response=client.post(f"/events/{event_id}/draft")
    assert draft_response.status_code==200,draft_response.text
    draft=draft_response.json(); draft_id=draft["draft_id"]
    assert any("Interlock" in observation for observation in draft["observations"])
    reviewed=client.post(f"/drafts/{draft_id}/review",json={"decision":"approve","reviewer":"Recorded evidence reviewer","comments":"Verified narrative preservation"})
    assert reviewed.status_code==200,reviewed.text
    assert reviewed.json()["knowledge"] is not None
    state["services"]=Services()
    assert client.get(f"/events/{event_id}/draft").json()["status"]=="approved"
    assert len(client.get("/knowledge").json())==1
    original=response.json()["original_file"]
    assert client.get(f'/events/{event_id}/files/{original["file_id"]}/download').content==narrative
    assert client.delete(f"/events/{event_id}").status_code==200
    state["services"]=Services()
    assert client.get("/events").json()==[] and client.get("/knowledge").json()==[]
    for path in (f"/events/{event_id}",f"/events/{event_id}/analysis",f"/events/{event_id}/draft",f"/drafts/{draft_id}",f'/events/{event_id}/files/{original["file_id"]}/download'):
        assert client.get(path).status_code==404
    assert not (tmp_path/"data"/"events"/event_id).exists()
    with state["services"].repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reviews WHERE event_id=?",(event_id,)).fetchone()[0]==0
    assert any(action["action"]=="review" for action in client.get("/audit").json())
