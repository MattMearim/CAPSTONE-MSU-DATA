"""Data-quality review and explicit derived-copy repairs through the public API."""
import hashlib
import json

import pytest

from test_mixed_api import environment


def send(client,path,contents,options=None,validate=False):
    return client.post(path,files={"file":("quality.csv",contents)},data={
        "options":json.dumps(options or {}),"validate":str(validate).lower()})


def test_malformed_file_receives_actionable_review_and_never_writes(environment):
    client,_,_=environment
    contents=b"time [s],voltage [V]\n0,1\n1,2,broken\n2,3\n"
    review=send(client,"/ingestion/quality",contents)
    assert review.status_code==200,review.text
    report=review.json()
    assert report["status"]=="blocked" and report["summary"]["error"]
    assert any(3 in issue["rows"] for issue in report["issues"])
    preview=send(client,"/ingestion/preview",contents,validate=True)
    assert preview.status_code==200,preview.text
    assert preview.json()["validation"]["valid"] is False
    assert preview.json()["quality"]["l1"]["status"]=="blocked"
    imported=send(client,"/ingestion/import",contents)
    assert imported.status_code==400
    assert client.get("/events").json()==[]


def test_explicit_shape_repair_is_previewed_and_preserves_original(environment):
    client,state,_=environment
    contents=b"time [s],voltage [V]\n0,1\n1,2,broken\n2,3\n3,4\n"
    settings={"event_id":"REPAIR-SHAPE","_repairs":[{"operation":"drop_malformed_rows","rows":[3]}]}
    preview=send(client,"/ingestion/preview",contents,settings,True)
    assert preview.status_code==200,preview.text
    payload=preview.json()
    assert payload["validation"]["valid"] is True,payload
    assert payload["quality"]["original_l1"]["status"]=="blocked"
    assert payload["quality"]["l1"]["status"]!="blocked"
    assert payload["repair_receipt"]
    assert client.get("/events").json()==[]
    imported=send(client,"/ingestion/import",contents,settings)
    assert imported.status_code==200,imported.text
    result=imported.json(); event=result["event"]
    assert event["provenance"]["checksum"]==hashlib.sha256(contents).hexdigest()
    assert event["metadata"]["repair_receipt"]==payload["repair_receipt"]
    original=result["original_file"]; derived=result["derived_file"]
    assert original["checksum"]==hashlib.sha256(contents).hexdigest()
    assert derived and derived["checksum"]!=original["checksum"]
    assert client.get(f'/events/REPAIR-SHAPE/files/{original["file_id"]}/download').content==contents
    repaired=client.get(f'/events/REPAIR-SHAPE/files/{derived["file_id"]}/download').content
    assert b"broken" not in repaired
    assert len(event["signals"][0]["values"])==3
    # Restarted storage still identifies the original and the derived copy separately.
    from frib_ds.bootstrap import Services
    state["services"]=Services()
    assert len(client.get("/events/REPAIR-SHAPE/files").json())==2
    assert client.get("/events/REPAIR-SHAPE").json()["metadata"]["repair_receipt"]==payload["repair_receipt"]


def test_invalid_measurements_can_be_marked_missing_without_touching_notes(environment):
    client,_,_=environment
    contents=b"time [s],pressure [kPa],note\n0,1,start\n1,NA,NA means a note here\n2,bad,keep this note\n3,1,normal\n4,1,normal\n"
    settings={"event_id":"REPAIR-CELLS","column_roles":{"pressure [kPa]":"numeric","note":"log"},
        "_repairs":[{"operation":"mark_missing_tokens","columns":["pressure [kPa]"]},{"operation":"drop_invalid_numeric_cells","rows":[4],"columns":["pressure [kPa]"]}],
        "quality_expectations":{"expected_interval_s":1}}
    preview=send(client,"/ingestion/preview",contents,settings,True)
    assert preview.status_code==200,preview.text
    assert preview.json()["validation"]["valid"],preview.json()
    result=send(client,"/ingestion/import",contents,settings)
    assert result.status_code==200,result.text
    event=result.json()["event"]
    assert event["signals"][0]["values"]==pytest.approx([1000,1000,1000])
    assert any(log["message"]=="NA means a note here" for log in event["logs"])
    assert any(log["message"]=="keep this note" for log in event["logs"])
    assert any(issue["code"]=="RECORDING_GAP" for issue in event["metadata"]["data_quality"]["issues"])


def test_unit_suggestions_do_not_assign_an_unconfirmed_physical_unit(environment):
    client,_,_=environment
    contents=b"time [s],pressure\n0,1\n1,2\n2,3\n"
    review=send(client,"/ingestion/quality",contents)
    assert review.status_code==200,review.text
    suggestions=review.json()["unit_suggestions"]
    assert any(s["column"]=="pressure" and s["requires_confirmation"] and not s["assigned"] for s in suggestions)
    before=send(client,"/ingestion/preview",contents,validate=True).json()
    assert before["event"]["signals"][0]["unit"]=="1"
    after=send(client,"/ingestion/preview",contents,{"source_units":{"pressure":"kPa"}},True).json()
    assert after["event"]["signals"][0]["unit"]=="Pa"
    assert after["event"]["signals"][0]["values"]==pytest.approx([1000,2000,3000])


def test_custom_quality_expectations_are_read_only_and_reused_in_analysis(environment):
    client,_,_=environment
    contents=b"time [s],voltage [V]\n0,1\n1,1\n2,1\n3,10\n4,10\n5,10\n"
    imported=send(client,"/ingestion/import",contents,{"event_id":"QUALITY-EXPECTATIONS"})
    assert imported.status_code==200,imported.text
    before=client.get("/events/QUALITY-EXPECTATIONS").json()
    expectations={"channels":{"voltage":{"expected_stable":True,"stability_tolerance":.2,"max":5}}}
    report=client.post("/events/QUALITY-EXPECTATIONS/quality",json={"expectations":expectations})
    assert report.status_code==200,report.text
    codes={issue["code"] for issue in report.json()["issues"]}
    assert {"STABILITY_EXCEEDED","OUT_OF_BOUNDS"}<=codes
    assert client.get("/events/QUALITY-EXPECTATIONS").json()==before
    analysis=client.post("/events/QUALITY-EXPECTATIONS/analyze",json={"expectations":expectations})
    assert analysis.status_code==200,analysis.text
    assert {"STABILITY_EXCEEDED","OUT_OF_BOUNDS"}<={issue["code"] for issue in analysis.json()["features"]["data_quality"]["issues"]}


def test_domain_analysis_does_not_interpolate_through_recording_gap(environment):
    client,_,_=environment
    contents=b"time [s],vibration [m/s^2]\n0,0\n1,1\n2,0\n20,1\n21,0\n22,1\n"
    imported=send(client,"/ingestion/import",contents,{"event_id":"GAP-GATE","domain":"mechanical"})
    assert imported.status_code==200,imported.text
    result=client.post("/events/GAP-GATE/analyze")
    assert result.status_code==200,result.text
    analysis=result.json()
    assert analysis["processor"]=="mixed_evidence_summary"
    assert not any(plot["kind"]=="fft" for plot in analysis["plot_specs"])
    assert any("withheld" in warning for warning in analysis["features"]["warnings"])
    assert not any("required mechanical engineering channels" in warning for warning in analysis["features"]["warnings"])


@pytest.mark.parametrize("changes",[
    {"_repairs":[{"operation":"fill_missing_with_zero"}]},
    {"_repairs":"drop_bad"},
    {"quality_expectations":{"expected_interval_s":0}},
    {"quality_expectations":{"channels":{"voltage":{"min":10,"max":1}}}},
])
def test_invalid_repairs_or_expectations_do_not_persist(environment,changes):
    client,_,_=environment
    contents=b"time [s],voltage [V]\n0,1\n1,2\n2,3\n"
    response=send(client,"/ingestion/import",contents,changes)
    assert response.status_code==400,response.text
    assert client.get("/events").json()==[]


def test_whole_file_quality_is_computed_before_preview_sampling(environment):
    client,_,_=environment
    contents=("time [s],voltage [V]\n"+"".join(f"{i},1\n" for i in range(1500))+"1500,999\n").encode()
    settings={"quality_expectations":{"channels":{"voltage":{"max":5}}}}
    response=send(client,"/ingestion/preview",contents,settings,True)
    assert response.status_code==200,response.text
    body=response.json()
    assert len(body["event"]["signals"][0]["values"])<=1000
    issue=next(i for i in body["quality"]["l2"]["issues"] if i["code"]=="OUT_OF_BOUNDS")
    assert issue["count"]==1 and 1500 in issue["timestamps_s"]


def test_legacy_view_uses_same_units_as_quality_without_rewriting_storage(environment):
    client,state,_=environment
    from frib_ds.models import EngineeringEvent,Provenance,Signal
    event=EngineeringEvent(event_id="LEGACY-QUALITY",domain="other",event_type="record",
        provenance=Provenance(source="legacy"),signals=[Signal(name="voltage",unit="mV",sample_rate_hz=1,timestamps_s=[0,1,2],values=[1000,2000,3000])])
    state["services"].repo.save_event(event)
    response=client.get("/events/LEGACY-QUALITY")
    assert response.status_code==200,response.text
    assert response.json()["signals"][0]["unit"]=="V"
    assert response.json()["signals"][0]["values"]==[1,2,3]
    report=client.post("/events/LEGACY-QUALITY/quality",json={"expectations":{"channels":{"voltage":{"max":2.5}}}})
    assert report.status_code==200,report.text
    assert next(i for i in report.json()["issues"] if i["code"]=="OUT_OF_BOUNDS")["count"]==1
    assert state["services"].repo.get_event("LEGACY-QUALITY").signals[0].unit=="mV"


def test_extreme_finite_values_cannot_persist_nonfinite_domain_results(environment):
    client,_,_=environment
    contents=("time [s],vibration [m/s^2]\n"+"".join(f"{i/10},{1e308 if i%2 else -1e308}\n" for i in range(40))).encode()
    imported=send(client,"/ingestion/import",contents,{"event_id":"NUMERIC-RANGE","domain":"mechanical"})
    assert imported.status_code==200,imported.text
    response=client.post("/events/NUMERIC-RANGE/analyze")
    assert response.status_code==200,response.text
    analysis=response.json()
    assert analysis["processor"]=="mixed_evidence_summary"
    assert any(issue["code"]=="NUMERICAL_RANGE" for issue in analysis["features"]["data_quality"]["issues"])
    json.dumps(analysis,allow_nan=False)
    assert client.get("/events/NUMERIC-RANGE").json()["signals"][0]["values"][0]==-1e308
