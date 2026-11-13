"""Repeatable, isolated L1/L2 presentation evidence; never uses saved user records.

Run: python scripts/run_l1_l2_demo.py --output deliverables/L1_L2_Presentation/evidence
Existing unrelated output files (including pytest-results.xml) are preserved.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from fastapi.testclient import TestClient
from frib_ds.api import main as api
from frib_ds.bootstrap import Services, get_services
from frib_ds.config import get_config
from frib_ds.ingestion import build_event
from frib_ds.ingestion.quality import assess_upload, repair_upload
from frib_ds.models import EngineeringEvent, Provenance, Signal, StateEvent
from frib_ds.processing.common import align_signals, clean_signal, fft_spectrum
from frib_ds.processing.registry import ProcessorRegistry
from frib_ds.quality import assess_event, validate_expectations
from frib_ds.units import convert_value, normalize_event_units, normalize_unit, parse_quantity, unit_catalog


def serial(value):
    if isinstance(value, bytes):
        return {"type":"bytes","size_bytes":len(value),"sha256":hashlib.sha256(value).hexdigest(),"text_preview":value[:500].decode("utf-8",errors="replace")}
    if isinstance(value,datetime): return value.isoformat()
    if isinstance(value,Path): return str(value)
    if isinstance(value,set): return sorted(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def codes(report):
    return sorted({item["code"] for item in report["issues"]})


def capture(values=None, times=None, unit="V", rate=10, name="voltage", domain="other", metadata=None):
    values = values if values is not None else [math.sin(i / 10) for i in range(100)]
    times = times if times is not None else [i / rate for i in range(len(values))]
    return EngineeringEvent(event_id="DEMO-QUALITY", domain=domain, event_type="presentation_fixture",
        metadata={"synthetic": True, **(metadata or {})}, provenance=Provenance(source="synthetic_presentation_fixture"),
        signals=[Signal(name=name, unit=unit, sample_rate_hz=rate, timestamps_s=times, values=values)])


def text_pdf():
    """Minimal text-based PDF, generated locally without font/download dependencies."""
    stream = b"BT /F1 12 Tf 50 740 Td (0 ms [INFO] mode=OFF) Tj 0 -20 Td (20 ms [WARN] mode=ON) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    result = bytearray(b"%PDF-1.4\n"); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    position = len(result); result.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n".encode())
    return bytes(result)


class Case:
    def __init__(self, runner, case_id, title, stage, features, scope):
        self.runner = runner
        self.record = {"id": case_id, "title": title, "stage": stage, "features": features,
            "status": "passed", "expected": [], "observed": {"checks": [], "details": {}},
            "steps": [f"Scope: {scope}"], "input_files": [], "artifacts": []}

    def check(self, name, observed, expected=True):
        passed = observed == expected
        self.record["expected"].append({"name": name, "value": expected})
        self.record["observed"]["checks"].append({"name": name, "expected": expected, "observed": observed, "passed": passed})
        if not passed: raise AssertionError(f"{name}: expected {expected!r}, observed {observed!r}")

    def near(self, name, observed, expected, tolerance=1e-9):
        actual = list(observed) if isinstance(expected, (list, tuple)) else observed
        valid = (len(actual) == len(expected) and all(math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance) for a,b in zip(actual,expected))) if isinstance(expected,(list,tuple)) else math.isclose(actual,expected,rel_tol=tolerance,abs_tol=tolerance)
        self.record["expected"].append({"name": name, "value": expected, "tolerance": tolerance})
        self.record["observed"]["checks"].append({"name": name, "expected": expected, "observed": actual, "tolerance": tolerance, "passed": valid})
        if not valid: raise AssertionError(f"{name}: expected {expected!r}, observed {actual!r}")

    def includes(self, name, actual, expected):
        self.check(name, sorted(set(actual) & set(expected)), sorted(expected))

    def reject(self, name, function, substring=""):
        try: function()
        except (ValueError, TypeError) as exc:
            self.check(name, substring.lower() in str(exc).lower())
            self.record["observed"]["details"][name] = {"error_type": type(exc).__name__, "message": str(exc)}
        else: self.check(name, "accepted", "rejected")

    def input(self, name, contents):
        path = self.runner.output / "demo_inputs" / name
        path.write_bytes(contents)
        relative = path.relative_to(self.runner.output).as_posix()
        self.record["input_files"].append(relative)
        return contents

    def artifact(self, name, value):
        path = self.runner.output / "artifacts" / f"{self.record['id']}-{name}.json"
        path.write_text(json.dumps(serial(value), indent=2, ensure_ascii=False, allow_nan=False,default=serial), encoding="utf-8")
        relative = path.relative_to(self.runner.output).as_posix()
        self.record["artifacts"].append(relative)
        return relative

    def report(self, report, key="report"):
        self.record["observed"]["details"][key] = report
        return report

    def response(self, response, expected=200, key=None):
        self.check(f"HTTP {response.request.method} {response.request.url.path}", response.status_code, expected)
        try: data = response.json()
        except ValueError: data = {"size_bytes": len(response.content)}
        if key: self.report(data, key)
        return data


class Runner:
    def __init__(self, output):
        self.output = output; self.records = []; self.plot_data = {}
        for name in ("demo_inputs", "artifacts", "cases"): (output / name).mkdir(parents=True, exist_ok=True)

    def case(self, case_id, title, stage, features, scope="deterministic helper"):
        def execute(function):
            case = Case(self, case_id, title, stage, features, scope)
            try: function(case)
            except Exception as exc:
                case.record["status"] = "failed"
                case.record["observed"]["error"] = {"type": type(exc).__name__, "message": str(exc)}
            relative = f"cases/{case_id}.json"
            case.record["artifacts"].append(relative)
            (self.output / relative).write_text(json.dumps(case.record, indent=2, ensure_ascii=False, allow_nan=False,default=serial), encoding="utf-8")
            self.records.append(case.record)
            print(f"{case.record['status'].upper():6} {case_id} {title}", flush=True)
            return function
        return execute

    def finish(self):
        summary = {"total": len(self.records), "passed": sum(r["status"] == "passed" for r in self.records), "failed": sum(r["status"] == "failed" for r in self.records)}
        payload = {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(), "project": "FRIB decision-support proof of concept", "summary": summary, "scenarios": self.records,
            "limitations": ["All inputs are generated demonstration fixtures; no facility records were used.", "API TestClient and deterministic helpers are exercised; this runner does not prove browser interaction or facility deployment readiness.", "Quality warnings identify review questions, not corruption, fault causes or operator negligence."]}
        (self.output / "scenario_results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False,default=serial), encoding="utf-8")
        (self.output / "plot_data.json").write_text(json.dumps(self.plot_data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        lines = ["# L1 / L2 observed demonstration results", "", f"Generated: {payload['generated_at']}", "", f"**{summary['passed']} passed; {summary['failed']} failed; {summary['total']} scenarios.**", "", "Every scenario ran against an isolated temporary data directory with mock AI, hash embeddings and SQLite. Existing application records were not accessed. This pack reports API/helper evidence, not a browser usability test.", "", "| ID | Stage | Result | Scenario |", "|---|---|---|---|"]
        for record in self.records:
            lines.append(f"| [{record['id']}](cases/{record['id']}.json) | {record['stage']} | {record['status']} | {record['title']} |")
        lines += ["", "Open scenario_results.json for expected/observed checks. demo_inputs contains generated sources; artifacts contains native event/analysis JSON suitable for plots. plot_data.json contains four measured chart datasets. Unrelated files in this directory are preserved on rerun."]
        (self.output / "DEMO_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps(summary), flush=True)
        return int(bool(summary["failed"]))


def demonstrate(r, client, state):
    def send(path, filename, contents, options=None, validate=False):
        return client.post(path, files={"file": (filename, contents, "application/octet-stream")}, data={"options": json.dumps(options or {}), "validate": str(validate).lower()})

    mixed = (b"time_ms,voltage [mV],temperature [C],mode,enabled,note\r\n"
        b"0,1000,20,RUNNING,true,[INFO] Beam enabled\r\n100,2 kV,21,WARNING,false,[WARN] Pressure noted\r\n200,500 mV,22,INTERLOCKED,true,[ERROR] Interlock reported\r\n")
    mixed_options = {"event_id": "DEMO-MIXED", "domain": "rf", "time_column": "time_ms", "time_unit": "ms",
        "column_roles": {"voltage [mV]": "numeric", "temperature [C]": "numeric", "mode": "category", "enabled": "category", "note": "log"},
        "signal_names": {"voltage [mV]": "voltage", "temperature [C]": "temperature"}}

    @r.case("L1-01", "Mixed CSV preview and canonical import", "L1", ["mixed_csv", "column_roles", "booleans", "severity_labels", "preview_no_write", "canonical_import"], "API TestClient")
    def mixed_case(c):
        c.input("mixed_units_and_states.csv", mixed)
        before = client.get("/events").json()
        preview = c.response(send("/ingestion/preview", "mixed.csv", mixed, mixed_options, True), key="preview")
        c.check("preview valid", preview["validation"]["valid"])
        c.check("preview persisted nothing", client.get("/events").json(), before)
        imported = c.response(send("/ingestion/import", "mixed.csv", mixed, mixed_options), key="import")
        event = imported["event"]; signals = {s["name"]:s for s in event["signals"]}
        c.near("SI voltage values", signals["voltage"]["values"], [1,2000,.5])
        c.near("Kelvin temperatures", signals["temperature"]["values"], [293.15,294.15,295.15])
        c.near("seconds timeline", signals["voltage"]["timestamps_s"], [0,.1,.2])
        c.includes("categorical states retained", [s["value"] for s in event["states"]], ["true","false","RUNNING","INTERLOCKED"])
        c.check("explicit log severities", sorted({log["level"] for log in event["logs"]}), ["ERROR","INFO","WARNING"])
        c.artifact("event", event)

    @r.case("L1-02", "Per-row units and explicit target mapping", "L1", ["per_row_units", "header_units", "quantity_suffix", "target_units"], "API TestClient")
    def per_row(c):
        data = c.input("per_row_gradient.csv", b"time [ms],gradient,gradient_unit,mode\n0,5,MV/m,READY\n10,6000,kV/m,RUN\n20,7000000,V/m,RUN\n")
        options={"event_id":"DEMO-ROW-UNITS","unit_columns":{"gradient":"gradient_unit"},"column_roles":{"gradient":"numeric","gradient_unit":"ignore","mode":"category"},"target_units":{"gradient":"MV/m"}}
        result=c.response(send("/ingestion/import","rowunits.csv",data,options),key="import")
        signal=result["event"]["signals"][0]
        c.check("canonical gradient label",signal["unit"],"V/m"); c.near("compatible per-row scales",signal["values"],[5e6,6e6,7e6])
        c.check("unit column excluded",len(result["event"]["signals"]),1); c.artifact("event",result["event"])

    @r.case("L1-03", "TXT, Markdown, LOG and text PDF", "L1", ["txt", "markdown", "log", "text_pdf", "narrative_states", "relative_time"], "API TestClient")
    def documents(c):
        results={}
        for extension in ("txt","md","log","pdf"):
            data=text_pdf() if extension=="pdf" else b"0 ms [INFO] mode=OFF\n20 ms [WARN] mode=ON\n40 ms [ERROR] review requested\n"
            c.input(f"operator_shift.{extension}",data)
            result=c.response(send("/ingestion/import",f"operator.{extension}",data,{"event_id":f"DEMO-TEXT-{extension.upper()}","domain":"rf"}))
            event=result["event"]; c.check(f"{extension} numeric channels",event["signals"],[])
            c.check(f"{extension} text extracted",len(event["logs"])>=2)
            c.check(f"{extension} original SHA",result["original_file"]["checksum"],hashlib.sha256(data).hexdigest())
            results[extension]=event
        c.report(results,"events"); c.artifact("event",results["log"])

    @r.case("L1-04", "ISO datetime and explicit ordinal timelines", "L1", ["iso_datetime", "datetime_anchor", "ordinal_time", "time_units"], "deterministic helper")
    def time_formats(c):
        data=c.input("iso_capture.csv",b"time,x [V]\n2026-10-10T12:00:00Z,1\n2026-10-10T12:00:02Z,2\n2026-10-10T12:00:03Z,3\n")
        event=build_event("iso.csv",data,{"time_unit":"datetime"})
        c.near("relative ISO seconds",event.signals[0].timestamps_s,[0,2,3])
        ordinal=build_event("ordinal.csv",b"reading [V],note\n1,start\n2,end\n",{})
        c.check("ordinal basis explicit",ordinal.metadata["import_summary"]["time_basis"],"row_index")
        c.check("ordinal no timing claims", "TIMING_UNAVAILABLE" in codes(assess_event(ordinal)))
        for unit,number in [("ns",1e9),("us",1e6),("ms",1000),("s",1),("min",1/60),("h",1/3600)]:
            sample=f"time,value [V]\n0,1\n{number},2\n".encode(); parsed=build_event("time.csv",sample,{"time_unit":unit})
            c.near(f"{unit} seconds",parsed.signals[0].timestamps_s[-1],1)
        c.artifact("event",event); c.report(ordinal.model_dump(mode="json"),"ordinal_event")

    @r.case("L1-05", "Strict JSON schema and raw versus normalized exports", "L1", ["json_schema", "boolean_rejection", "timestamp_contract", "raw_export", "normalized_export", "provenance"], "API TestClient")
    def json_contract(c):
        event=capture([1000,2000,3000],times=[0,1,2],unit="mV",rate=1); event.event_id="DEMO-JSON"
        payload=event.model_dump(mode="json"); c.input("engineering_event.json",json.dumps(payload,indent=2).encode())
        c.response(client.post("/events",json=payload)); created=c.response(client.get("/events/DEMO-JSON")); c.check("stored SI unit",created["signals"][0]["unit"],"V")
        raw=c.response(client.get("/events/DEMO-JSON/download?format=json")); normalized=c.response(client.get("/events/DEMO-JSON/download?format=normalized-json"))
        c.near("raw values retained",raw["signals"][0]["values"],[1000,2000,3000]); c.near("normalized values",normalized["signals"][0]["values"],[1,2,3])
        c.check("SI CSV export available",client.get("/events/DEMO-JSON/download?format=csv").status_code,200)
        for index,changes in enumerate([{"values":[True,False,True]},{"timestamps_s":[0,0,1]},{"values":[1,2]}]):
            bad=json.loads(json.dumps(payload)); bad["event_id"]=f"DEMO-BAD-{index}"; bad["signals"][0].update(changes)
            c.response(client.post("/events",json=bad),422)
        c.artifact("event",normalized); c.report(raw,"raw_event")

    @r.case("L1-06", "Structural and encoding detector inventory", "L1", ["invalid_upload","unreadable_text","empty_file","empty_header","duplicate_headers","csv_syntax","no_data_rows","column_limit","unreadable_document"], "deterministic helper")
    def structures(c):
        samples=[("empty.csv",b"","invalid_upload"),("utf8.csv",b"\xff","unreadable_text"),("binary.csv",b"\x00","unreadable_text"),("bom.csv",b"\xef\xbb\xbf","empty_file"),
            ("header.csv",b"x,\n1,2\n","empty_header"),("duplicate.csv",b"x,x\n1,2\n","duplicate_headers"),("quotes.csv",b'x [V]\n"unfinished',"csv_syntax"),("nodata.csv",b"x [V]\n","no_data_rows"),
            ("wide.csv",(",".join(f"c{i}" for i in range(65))+"\n"+",".join("1" for _ in range(65))+"\n").encode(),"column_limit"),("broken.pdf",b"not a PDF","unreadable_document")]
        for filename,data,code in samples:
            c.input(filename,data); report=c.report(assess_upload(filename,data),filename)
            c.check(f"{filename} detected {code}",code in codes(report)); c.check(f"{filename} blocked",report["status"],"blocked")

    @r.case("L1-07", "Combined malformed-row and missing-data findings", "L1", ["row_shape","missing_tokens","mixed_numeric_text","duplicate_rows","time_reversal","duplicate_timestamps","missing_cells","possible_truncation"], "API TestClient and deterministic helper")
    def corrupt(c):
        data=c.input("quality_corrupt.csv",b"time [s],pressure [kPa],mode\n0,1,OFF\n2,NAN,ON\n1,operator note,ON\n1,operator note,ON\n3,,OFF\n4,9")
        options={"column_roles":{"pressure [kPa]":"numeric","mode":"category"}}
        report=c.report(assess_upload("bad.csv",data,options)); c.includes("all combined flags",codes(report),c.record["features"])
        before=client.get("/events").json(); response=c.response(send("/ingestion/import","bad.csv",data,options),400,key="blocked_import")
        c.check("corrupt import atomic",client.get("/events").json(),before)

    @r.case("L1-08", "Time declaration, invalid time and legitimate ties", "L1", ["unsupported_time_unit","time_unit_unconfirmed","invalid_timestamp","inferred_time","disjoint_timestamp_ties"], "deterministic helper")
    def timing_flags(c):
        fixtures=[(b"time [V],x [V]\n0,1\n1,2\n",{},"unsupported_time_unit"),(b"time,x [V]\n0,1\n1,2\n",{},"time_unit_unconfirmed"),
            (b"time [s],x [V]\n0,1\nbad,2\n1,3\n",{},"invalid_timestamp"),(b"x [V]\n1\n2\n",{},"inferred_time")]
        for i,(data,options,code) in enumerate(fixtures):
            c.input(f"time_flags_{i}.csv",data); report=c.report(assess_upload("time.csv",data,options),code); c.check(code,code in codes(report))
        data=b"time [s],a [V],b [V]\n0,1,\n0,,2\n1,3,4\n"; report=c.report(assess_upload("ties.csv",data),"ties")
        c.check("disjoint ties warning",next(x["severity"] for x in report["issues"] if x["code"]=="duplicate_timestamps"),"warning")
        c.check("disjoint ties accepted",len(build_event("ties.csv",data,{}).signals),2)

    @r.case("L1-09", "Numeric, sentinel and unit conflict detectors", "L1", ["unsupported_unit","nonfinite_values","invalid_numeric","possible_sentinel","incompatible_units","missing_unit","mixed_unit_scales","insufficient_numeric_samples"], "deterministic helper")
    def numeric_flags(c):
        fixtures=[(b"time [s],x [dBm]\n0,1\n1,2\n",{},["unsupported_unit"]),
            (b"time [s],x [V]\n0,-9999\n1,2\n2,Infinity\n3,1e999\n",{},["possible_sentinel","nonfinite_values","invalid_numeric"]),
            (b"time [s],x [V]\n0,1 V\n1,2 kV\n2,3 Pa\n3,4 V\n",{},["mixed_unit_scales","incompatible_units"]),
            (b"time [s],pressure\n0,1\n1,2\n",{},["missing_unit"]),(b"time [s],x [V]\n0,1\n1,bad\n",{},["insufficient_numeric_samples"]),
            (b"time [s],x,unit\n0,1 V,V\n1,2 V,Pa\n2,3 V,V\n",{"unit_columns":{"x":"unit"}},["incompatible_units"])]
        for i,(data,options,expected) in enumerate(fixtures):
            c.input(f"numeric_flags_{i}.csv",data); report=c.report(assess_upload("numeric.csv",data,options),f"fixture_{i}"); c.includes(f"fixture {i} flags",codes(report),expected)

    @r.case("L1-10", "Unit suggestions require confirmation", "L1", ["high_confidence_units","medium_suffix_suggestion","low_name_suggestion","temperature_ambiguity","no_unit_inference"], "API TestClient and deterministic helper")
    def suggestions(c):
        details={}
        for column,confidence,expected in [("voltage [mV]","high",{"mV"}),("voltage_mV","medium",{"mV"}),("temperature","low",{"C","K","F"}),("temperature_difference","low",{"delta_C","delta_K","delta_F"})]:
            data=f"time [s],{column}\n0,20\n1,21\n".encode(); report=assess_upload("suggest.csv",data); suggestion=report["unit_suggestions"][0]
            c.check(f"{column} never assigned",suggestion["assigned"],False); c.check(f"{column} confirmation",suggestion["requires_confirmation"])
            c.includes(f"{column} candidates",[item["unit"] for item in suggestion["candidates"]],expected)
            c.check(f"{column} confidence",any(item["confidence"]==confidence for item in suggestion["candidates"]))
            details[column]=report
        data=c.input("unconfirmed_pressure.csv",b"time [s],pressure\n0,1\n1,2\n")
        unconfirmed=c.response(send("/ingestion/preview","pressure.csv",data,{},True)); confirmed=c.response(send("/ingestion/preview","pressure.csv",data,{"source_units":{"pressure":"kPa"}},True))
        c.check("unconfirmed dimensionless",unconfirmed["event"]["signals"][0]["unit"],"1"); c.near("confirmed Pa",confirmed["event"]["signals"][0]["values"],[1000,2000]); c.report(details,"suggestions")

    @r.case("L1-11", "Explicit row repairs, sorting and missing tokens", "L1", ["drop_malformed_rows","drop_exact_duplicate_rows","mark_missing_tokens","sort_by_time","repair_receipt","physical_source_rows"], "deterministic helper")
    def row_repairs(c):
        data=c.input("repair_workshop.csv",b'time [s],x [V],mode,note\n2,2,NA,"retain, quoted text"\n0,NA,ON,"line one\nline two"\n0,NA,ON,"line one\nline two"\n1,1,OFF,done\n3,9\n')
        options={"column_roles":{"x [V]":"numeric","mode":"category","note":"log"}}
        repairs=[{"operation":"drop_malformed_rows","rows":[8]},{"operation":"drop_exact_duplicate_rows"},{"operation":"mark_missing_tokens","columns":["x [V]"]},{"operation":"sort_by_time"}]
        effective,receipt=repair_upload("repair.csv",data,options,repairs)
        c.input("reviewed_workshop.csv",effective); c.report(receipt,"receipt")
        c.check("accurate change counts",[x["count"] for x in receipt["changes"]],[1,1,1,3])
        c.check("original SHA",receipt["before_checksum"],hashlib.sha256(data).hexdigest()); c.check("derived SHA",receipt["after_checksum"],hashlib.sha256(effective).hexdigest())
        c.check("multiline prose preserved",b"line one\nline two" in effective); c.check("literal categorical NA preserved",b"2,2,NA" in effective)
        event=build_event("reviewed.csv",effective,options); c.check("missing measurement not filled",len(event.signals[0].values),2)
        again,repeated=repair_upload("reviewed.csv",effective,options,[{"operation":"drop_exact_duplicate_rows"},{"operation":"mark_missing_tokens","columns":["x [V]"]},{"operation":"sort_by_time"}])
        c.check("repair idempotency",again,effective); c.check("second change counts",[x["count"] for x in repeated["changes"]],[0,0,0]); c.artifact("event",event)

    @r.case("L1-12", "Selected cell repairs preserve originals and notes", "L1", ["drop_invalid_numeric_cells","repair_original_preservation","derived_attachment","repair_restart","source_vs_copy_rows"], "API TestClient")
    def cell_repairs(c):
        data=c.input("selected_cell_repairs.csv",b"time [s],pressure [kPa],note\n0,1,start\n1,NA,NA means a note here\n2,bad,keep this note\n3,1,normal\n4,1,normal\n")
        options={"event_id":"DEMO-REPAIRS","column_roles":{"pressure [kPa]":"numeric","note":"log"},"_repairs":[{"operation":"mark_missing_tokens","columns":["pressure [kPa]"]},{"operation":"drop_invalid_numeric_cells","rows":[4],"columns":["pressure [kPa]"]}],"quality_expectations":{"expected_interval_s":1}}
        preview=c.response(send("/ingestion/preview","repair.csv",data,options,True)); c.check("reviewed preview valid",preview["validation"]["valid"])
        result=c.response(send("/ingestion/import","repair.csv",data,options),key="import")
        for key,expected in [("original_file",data)]:
            file=result[key]; response=client.get(f"/events/DEMO-REPAIRS/files/{file['file_id']}/download"); c.check("original exact bytes",response.content,expected)
        derived=result["derived_file"]; c.check("derived separate",derived["checksum"]!=result["original_file"]["checksum"])
        event=result["event"]; c.near("three measured samples only",event["signals"][0]["values"],[1000,1000,1000])
        c.check("notes survive repairs",any(log["message"]=="keep this note" for log in event["logs"]))
        c.check("original row basis",event["metadata"]["upload_quality"]["location_basis"],"original_source_rows")
        c.check("copy row basis",event["metadata"]["effective_upload_quality"]["location_basis"],"reviewed_copy_rows")
        state["services"]=Services(); stored=c.response(client.get("/events/DEMO-REPAIRS")); c.check("receipt survives restart",stored["metadata"]["repair_receipt"],event["metadata"]["repair_receipt"]); c.artifact("event",event)

    @r.case("L1-13", "Repair whitelist rejects guesses and ambiguous edits", "L1", ["repair_whitelist","no_fill","no_interpolation","no_unit_deletion","timestamp_repair_rejection","numeric_only_repairs"], "deterministic helper")
    def whitelist(c):
        data=b"time [s],x [V],note\n0,1,NA\n1,2,operator\n"
        invalid=[{"operation":"interpolate"},{"operation":"fill","value":0},{"operation":"drop_malformed_rows"},{"operation":"drop_invalid_numeric_cells","columns":["x [V]"]},{"operation":"mark_missing_tokens","columns":["note"]},{"operation":"mark_missing_tokens","columns":["x [V]"],"tokens":["operator"]},{"operation":"sort_by_time","rows":[2]}]
        for i,operation in enumerate(invalid): c.reject(f"repair {i} refused",lambda op=operation:repair_upload("safe.csv",data,{},[op]))
        conflict=b"time [s],x [V]\n0,1\n1,2 Pa\n2,3\n"
        c.reject("unit conflict cannot be deleted",lambda:repair_upload("unit.csv",conflict,{},[{"operation":"drop_invalid_numeric_cells","columns":["x [V]"],"rows":[3]}]),"Unit errors")
        c.reject("unreadable time cannot be sorted",lambda:repair_upload("time.csv",b"time [s],x [V]\n0,1\nbad,2\n",{},[{"operation":"sort_by_time"}]),"Every timestamp")

    @r.case("L1-14", "Bounded inspection and upload limits", "L1", ["inspection_limit","byte_limit","row_limit","column_limit","bounded_examples","accurate_counts"], "API TestClient and patched helper bounds (small fixtures)")
    def bounds(c):
        from frib_ds.ingestion import common, quality
        data=b"time [s],x [V]\n0,1\n1,2\n"
        for attr,value in [("MAX_CELLS",3),("MAX_ROWS",1)]:
            with patch.object(quality,attr,value):
                report=c.report(assess_upload("limit.csv",data),attr); c.check(f"{attr} enforced","inspection_limit" in codes(report))
                c.reject(f"{attr} cannot repair partial inspection",lambda:repair_upload("limit.csv",data,{},[{"operation":"drop_exact_duplicate_rows"}]),"prevent safe repair")
        with patch.object(common,"MAX_BYTES",10): c.check("helper byte bound","invalid_upload" in codes(assess_upload("limit.csv",data)))
        with patch.object(api,"MAX_DOCUMENT_BYTES",10): c.response(send("/ingestion/preview","limit.csv",data),413)
        many=b"time [s],x [V]\n"+b"0,1\n"*41+b"1,2\n"; report=c.report(assess_upload("many.csv",many),"bounded_report")
        duplicate=next(x for x in report["issues"] if x["code"]=="duplicate_rows"); c.check("all duplicates counted",duplicate["count"],40); c.check("locations capped",len(duplicate["rows"]),25)

    @r.case("L1-15", "Skip policy and invalid mapping validation", "L1", ["explicit_skip_policy","invalid_options","skip_unit_anchor","atomic_invalid_import"], "API TestClient and deterministic helper")
    def policies(c):
        data=c.input("explicit_skip.csv",b"time [s],x [V]\n0,1\n1,NAN\nno time,5\n2,3\n")
        report=c.report(assess_upload("skip.csv",data,{"invalid_rows":"skip"})); c.check("skip requires review",report["status"],"review")
        event=build_event("skip.csv",data,{"invalid_rows":"skip"}); c.near("only measured accepted values",event.signals[0].values,[1,3])
        anchors=build_event("anchors.csv",b"time [s],reading\ninvalid,1 Pa\n0,1 V\n1,2 V\n",{"invalid_rows":"skip"}); c.check("skipped time cannot define unit",anchors.signals[0].unit,"V")
        for options in [{"metadata":"bad"},{"time_unit":[]},{"column_roles":{"x [V]":{}}}]: c.check("invalid options reported","invalid_options" in codes(assess_upload("bad.csv",data,options)))
        before=client.get("/events").json()
        for options in ["not-json","[]","null"]:
            response=client.post("/ingestion/import",files={"file":("bad.csv",data)},data={"options":options}); c.response(response,400)
        c.check("bad options no writes",client.get("/events").json(),before)

    @r.case("L1-16", "Preview sampling validates the complete capture", "L1", ["preview_sampling","full_file_validation","full_import_retention"], "API TestClient")
    def preview_limits(c):
        data=("time [s],voltage [V]\n"+"".join(f"{i},1\n" for i in range(1500))+"1500,999\n").encode(); c.input("preview_1501.csv",data)
        options={"event_id":"DEMO-PREVIEW","quality_expectations":{"channels":{"voltage":{"max":5}}}}
        result=c.response(send("/ingestion/preview","large.csv",data,options,True)); c.check("preview bounded",len(result["event"]["signals"][0]["values"])<=1000)
        issue=next(x for x in result["quality"]["l2"]["issues"] if x["code"]=="OUT_OF_BOUNDS"); c.check("last-row quality included",issue["timestamps_s"],[1500.0])
        full=c.response(send("/ingestion/import","large.csv",data,options)); c.check("full import not sampled",len(full["event"]["signals"][0]["values"]),1501)
        bad=data.replace(b"1500,999",b"1500,invalid"); result=c.response(send("/ingestion/preview","badlast.csv",bad,{},True)); c.check("last invalid row rejected",result["validation"]["valid"],False)
        c.report(result,"invalid_last_row")

    @r.case("L1-17", "Evidence file lifecycle and duplicate protection", "L1", ["file_add_download_delete","exact_original_bytes","duplicate_409","restart_persistence"], "API TestClient")
    def file_lifecycle(c):
        before=c.response(client.get("/events/DEMO-MIXED")); files=client.get("/events/DEMO-MIXED/files").json(); original=files[0]
        downloaded=client.get(f"/events/DEMO-MIXED/files/{original['file_id']}/download"); c.check("original bytes exact",downloaded.content,mixed)
        c.check("original SHA exact",original["checksum"],hashlib.sha256(downloaded.content).hexdigest())
        addition=b"[INFO] Synthetic attachment for presentation\r\n"; metadata=c.response(client.post("/events/DEMO-MIXED/files",files={"file":("additional.log",addition)}))
        c.check("new file SHA",metadata["checksum"],hashlib.sha256(addition).hexdigest()); c.check("download new file",client.get(f"/events/DEMO-MIXED/files/{metadata['file_id']}/download").content,addition)
        c.response(client.delete(f"/events/DEMO-MIXED/files/{metadata['file_id']}")); c.response(client.get(f"/events/DEMO-MIXED/files/{metadata['file_id']}/download"),404)
        c.response(send("/ingestion/import","mixed.csv",mixed.replace(b"1000,20",b"9999,20"),mixed_options),409)
        state["services"]=Services(); c.check("capture persists unchanged",client.get("/events/DEMO-MIXED").json(),before)

    @r.case("L1-18", "Narrative review and cascade deletion after restart", "L1/L2", ["narrative_analysis","human_review","cascade_delete","audit","restart_delete"], "API TestClient")
    def review_lifecycle(c):
        event_id="DEMO-TEXT-LOG"; analysis=c.response(client.post(f"/events/{event_id}/analyze")); c.check("narrative descriptive processor",analysis["processor"],"mixed_evidence_summary")
        draft=c.response(client.post(f"/events/{event_id}/draft")); review=c.response(client.post(f"/drafts/{draft['draft_id']}/review",json={"decision":"approve","reviewer":"Presentation demonstration reviewer","comments":"Synthetic fixture reviewed for evidence preservation"}))
        c.check("reviewed knowledge created",review["knowledge"] is not None); state["services"]=Services()
        c.check("approved draft persisted",client.get(f"/events/{event_id}/draft").json()["status"],"approved")
        c.response(client.delete(f"/events/{event_id}")); state["services"]=Services()
        for suffix in ("","/analysis","/draft","/files"): c.response(client.get(f"/events/{event_id}{suffix}"),404)
        c.check("knowledge cascade",all(x["event_id"]!=event_id for x in client.get("/knowledge").json()))
        c.check("audit retained",any(x["action"]=="review" for x in client.get("/audit").json())); c.artifact("analysis",analysis)

    @r.case("UNITS-01", "Every registered unit round-trips through canonical SI", "L1/L2", ["unit_catalog","all_unit_families","case_sensitive_prefix","temperature_offset","temperature_difference","quantity_parser"], "API TestClient and deterministic helper")
    def units_all(c):
        catalog=c.response(client.get("/units")); results=[]
        for item in catalog:
            source=item["symbol"]; canonical=item["canonical_unit"]; converted=convert_value(2.5,source,canonical); restored=convert_value(converted,canonical,source)
            c.near(f"{source} canonical roundtrip",restored,2.5); results.append({"unit":source,"canonical":canonical,"input":2.5,"converted":converted,"roundtrip":restored})
        c.near("mV prefix",convert_value(1,"mV","V"),.001); c.near("MV prefix",convert_value(1,"MV","V"),1e6)
        c.near("F absolute offset",convert_value(32,"F","C"),0); c.near("delta offset zero",convert_value(18,"delta_F","delta_K"),10)
        c.check("delta alias",normalize_unit("Δ°C"),"delta_C"); c.check("scientific quantity",parse_quantity("1.5e3 mV"),(1500.0,"mV")); c.report(results,"roundtrips")

    @r.case("UNITS-02", "Unknown, incompatible and nonfinite conversions rejected", "L1/L2", ["incompatible_dimensions","unknown_units","boolean_rejection","nonfinite_rejection","conversion_overflow"], "API TestClient and deterministic helper")
    def units_bad(c):
        for source,target in [("V","W"),("C","delta_K"),("delta_C","K"),("mv","V"),("dBm","W")]: c.response(client.post("/units/convert",json={"value":1,"from_unit":source,"to_unit":target}),400)
        for value in (True,"NaN","1e999",None): c.response(client.post("/units/convert",json={"value":value,"from_unit":"V","to_unit":"mV"}),422)
        c.reject("overflow refused",lambda:convert_value(1e308,"MV","V"),"finite")

    @r.case("UNITS-03", "Normalization copies evidence and retains legacy warnings", "L1/L2", ["normalization_nonmutation","conversion_provenance","normalization_idempotency","legacy_unknown_preserved","legacy_missing_preserved"], "deterministic helper")
    def normalize(c):
        event=capture([1000,2000],unit="mV"); blank=capture([1,2],unit="",name="blank").signals[0]; unknown=capture([1,2],unit="arb",name="unknown").signals[0]; event.signals.extend([blank,unknown])
        before=event.model_dump(); converted=normalize_event_units(event); repeated=normalize_event_units(converted)
        c.check("raw model unchanged",event.model_dump(),before); c.near("SI conversion",converted.signals[0].values,[1,2])
        c.check("blank unit remains blank",converted.signals[1].unit,""); c.check("unknown remains arb",converted.signals[2].unit,"arb")
        c.check("two explicit legacy warnings",len(converted.metadata["unit_normalization"]["warnings"]),2)
        c.check("conversion original unit idempotent",repeated.signals[0].metadata["unit_conversion"]["original_unit"],"mV"); c.artifact("event",converted)

    @r.case("L2-01", "Good captures and real zero readings", "L2", ["good_capture","zero_not_missing","pure_assessment"], "deterministic helper")
    def good(c):
        event=capture(); before=event.model_dump(); report=c.report(assess_event(event)); c.check("good status",report["status"],"ok"); c.check("pure assessment",event.model_dump(),before)
        report=c.report(assess_event(capture([0,1,0,2,0,3,0])),"zeros"); c.check("zero not nonfinite","NONFINITE_VALUES" not in codes(report)); c.artifact("event",event)

    @r.case("L2-02", "Potential flatline runs", "L2", ["FLATLINE_RUN","flatline_samples","conservative_warning"], "deterministic helper")
    def flatline(c):
        event=capture([2.5]*20); report=c.report(assess_event(event)); issue=next(x for x in report["issues"] if x["code"]=="FLATLINE_RUN")
        c.check("one stuck run",issue["count"],1); c.check("stable real signal remains possible","genuinely stable" in issue["message"]); c.check("no values removed",len(event.signals[0].values),20); c.artifact("event",event)

    @r.case("L2-03", "Robust isolated spike and sustained step", "L2", ["ISOLATED_SPIKE","BASELINE_CHANGE","change_separation"], "deterministic helper")
    def changes(c):
        spike=capture([0]*10+[10]+[0]*10); step=capture([0]*20+[10]*20)
        sp=c.report(assess_event(spike),"spike"); st=c.report(assess_event(step),"step")
        c.check("spike detected","ISOLATED_SPIKE" in codes(sp)); c.check("spike not sustained step","BASELINE_CHANGE" not in codes(sp))
        c.check("step detected","BASELINE_CHANGE" in codes(st)); c.check("step not spike","ISOLATED_SPIKE" not in codes(st)); c.artifact("event",step)

    @r.case("L2-04", "Boundary changes and smooth-trend negative control", "L2", ["BOUNDARY_JUMP","boundary_context","smooth_trend_control"], "deterministic helper")
    def boundary(c):
        for key,values,row in [("end",[1]*9+[10],10),("start",[10]+[1]*9,2)]:
            report=c.report(assess_event(capture(values)),key); issue=next(x for x in report["issues"] if x["code"]=="BOUNDARY_JUMP"); c.check(f"{key} sample position",issue["rows"],[row]); c.check(f"{key} context warning","context is insufficient" in issue["message"])
        report=c.report(assess_event(capture([i/100 for i in range(100)])),"smooth"); c.check("smooth trend no abrupt flags",not ({"BOUNDARY_JUMP","ISOLATED_SPIKE","BASELINE_CHANGE"}&set(codes(report))))

    @r.case("L2-05", "Configured recording gap with bounded intervals", "L2", ["RECORDING_GAP","expected_interval_s","gap_intervals","estimated_missing_count"], "deterministic helper")
    def explicit_gap(c):
        event=capture([1,2,3,4,5],times=[0,.1,.2,.6,.7]); report=c.report(assess_event(event,{"expected_interval_s":.1})); issue=next(x for x in report["issues"] if x["code"]=="RECORDING_GAP")
        c.check("one configured cadence gap",issue["count"],1); c.check("estimated missing positions",issue["intervals"][0]["estimated_missing_samples"],3)
        c.check("accepted sample basis",report["location_basis"],"accepted_sample_index"); c.artifact("event",event)
        r.plot_data["recording_gap"]={"series":[{"name":"Before gap","x":[0,.1,.2],"y":[1,2,3]},{"name":"After gap","x":[.6,.7],"y":[4,5]}],"y_label":"Voltage (V)","annotation":"Gap 0.2–0.6 s; configured cadence 0.1 s; 3 missing positions estimated."}

    @r.case("L2-06", "Estimated cadence detects one missing position", "L2", ["POTENTIAL_RECORDING_GAP","robust_cadence","single_missing_position"], "deterministic helper")
    def estimated_gap(c):
        times=[i*.1 for i in range(1001) if i!=500]; event=capture([i/1000 for i in range(1000)],times=times); report=c.report(assess_event(event)); issue=next(x for x in report["issues"] if x["code"]=="POTENTIAL_RECORDING_GAP")
        c.check("single possible gap",issue["count"],1); c.check("no proved missing count","estimated_missing_samples" not in issue["intervals"][0]); c.check("conservative certainty","not confirmed" in issue["message"])

    @r.case("L2-07", "Irregular acquisition and sample-rate mismatch", "L2", ["IRREGULAR_CADENCE","SAMPLE_RATE_MISMATCH","timestamp_authority"], "deterministic helper")
    def irregular(c):
        report=c.report(assess_event(capture([1,2,3,4,5,6],times=[0,1,2.4,3.4,4.8,5.8],rate=1)),"irregular"); c.check("irregular flag","IRREGULAR_CADENCE" in codes(report))
        event=capture([1,2,3,4,5],times=[0,1,2,3,4],rate=100); report=c.report(assess_event(event),"rate"); c.check("declared rate mismatch","SAMPLE_RATE_MISMATCH" in codes(report)); c.check("declared evidence unchanged",event.signals[0].sample_rate_hz,100)

    @r.case("L2-08", "Operator stability tolerance and SI bounds", "L2", ["STABILITY_EXCEEDED","OUT_OF_BOUNDS","absolute_si_tolerance","bounded_issue_locations"], "API TestClient and deterministic helper")
    def stability(c):
        event=capture([1,1,1,10,10,10],times=[0,1,2,3,4,5],rate=1); settings={"channels":{"voltage":{"expected_stable":True,"stability_tolerance":.2,"min":0,"max":5}}}; report=c.report(assess_event(event,settings))
        c.includes("stability and bounds",codes(report),["STABILITY_EXCEEDED","OUT_OF_BOUNDS"]); c.check("three high values",next(x["count"] for x in report["issues"] if x["code"]=="OUT_OF_BOUNDS"),3)
        c.artifact("event",event); r.plot_data["stability"]={"series":[{"name":"Observed voltage","x":event.signals[0].timestamps_s,"y":event.signals[0].values}],"y_label":"Voltage (V)","annotation":"Step 1 to 10 V; absolute stability tolerance 0.2 V; upper bound 5 V."}
        before=client.get("/events/DEMO-MIXED").json(); response=c.response(client.post("/events/DEMO-MIXED/quality",json={"expectations":{"channels":{"voltage":{"max":5}}}})); c.check("read-only custom assessment",client.get("/events/DEMO-MIXED").json(),before)
        c.check("stored-SI threshold detected","OUT_OF_BOUNDS" in codes(response))

    @r.case("L2-09", "Missing and unknown legacy signal units", "L2", ["UNSPECIFIED_UNIT","UNKNOWN_UNIT","no_name_based_units"], "deterministic helper")
    def l2_units(c):
        for unit,code in [("","UNSPECIFIED_UNIT"),("arb","UNKNOWN_UNIT")]:
            event=capture(unit=unit,name="pressure"); report=c.report(assess_event(event),code); c.check(code,code in codes(report)); c.check(f"{code} label preserved",event.signals[0].unit,unit)

    @r.case("L2-10", "Duplicate channel data and unequal coverage", "L2", ["DUPLICATE_SIGNAL_DATA","CHANNEL_COVERAGE"], "deterministic helper")
    def coverage(c):
        event=capture(); mirror=event.signals[0].model_copy(deep=True); mirror.name="mirror"; short=Signal(name="short",unit="V",sample_rate_hz=10,timestamps_s=[i/10 for i in range(20,70)],values=[i/3 for i in range(50)]); event.signals.extend([mirror,short])
        report=c.report(assess_event(event)); c.includes("copy and coverage findings",codes(report),["DUPLICATE_SIGNAL_DATA","CHANNEL_COVERAGE"]); c.artifact("event",event)

    @r.case("L2-11", "Required channels and unmatched expectation names", "L2", ["MISSING_CHANNEL","UNMATCHED_EXPECTATION","self_contained_expectations"], "deterministic helper")
    def required(c):
        settings={"required_channels":["pressure","voltage"],"channels":{"voltag":{"min":0}}}; report=c.report(assess_event(capture(),settings)); c.includes("mapping gaps",codes(report),["MISSING_CHANNEL","UNMATCHED_EXPECTATION"]); c.check("applied settings retained",report["expectations"]["required_channels"],["pressure","voltage"])

    @r.case("L2-12", "Known skipped-cell counts remain visible", "L2", ["BLANK_VALUES_SKIPPED","INVALID_VALUES_SKIPPED","no_missing_fill"], "deterministic helper")
    def skipped(c):
        event=capture(); event.signals[0].metadata.update(blank_cells_skipped=7,invalid_cells_skipped=3); report=c.report(assess_event(event)); c.includes("known skip counts",codes(report),["BLANK_VALUES_SKIPPED","INVALID_VALUES_SKIPPED"])
        c.check("blank count",next(x["count"] for x in report["issues"] if x["code"]=="BLANK_VALUES_SKIPPED"),7); c.check("invalid count",next(x["count"] for x in report["issues"] if x["code"]=="INVALID_VALUES_SKIPPED"),3)

    @r.case("L2-13", "Potential categorical chatter", "L2", ["CATEGORY_CHATTER","categorical_timing"], "deterministic helper")
    def chatter(c):
        event=capture(); event.states=[StateEvent(name="enabled",value="ON" if i%2 else "OFF",timestamp_s=i*.01) for i in range(10)]; report=c.report(assess_event(event)); issue=next(x for x in report["issues"] if x["code"]=="CATEGORY_CHATTER"); c.check("eight alternating reversals",issue["count"],8); c.check("legitimate changes possible","legitimate" in issue["message"]); c.artifact("event",event)

    @r.case("L2-14", "Narrative-only and ordinal timing limits", "L2", ["NO_NUMERIC_SIGNALS","TIMING_UNAVAILABLE","ordinal_skips_elapsed_checks"], "deterministic helper")
    def no_timing(c):
        event=EngineeringEvent(event_id="DEMO-NO-NUMERIC",domain="rf",event_type="record",logs=[{"timestamp_s":0,"message":"Synthetic operator note"}],provenance={"source":"synthetic_presentation_fixture"}); report=c.report(assess_event(event),"narrative"); c.check("no numeric info","NO_NUMERIC_SIGNALS" in codes(report))
        ordinal=capture([1,2,3,4,5],times=[0,1,5,6,7],rate=100,metadata={"import_summary":{"time_basis":"row_index"}}); report=c.report(assess_event(ordinal,{"expected_interval_s":.01}),"ordinal")
        c.check("timing unavailable","TIMING_UNAVAILABLE" in codes(report)); c.check("no elapsed claims",not ({"RECORDING_GAP","POTENTIAL_RECORDING_GAP","IRREGULAR_CADENCE","SAMPLE_RATE_MISMATCH"}&set(codes(report))))

    @r.case("L2-15", "Defensive checks for invalid adapter contracts", "L2", ["NONFINITE_VALUES","INVALID_TIMESTAMPS","defensive_contract_check"], "unvalidated adapter helper (not public ingestion)")
    def invalid_adapter(c):
        event=capture(); event.signals[0].values[3]=float("nan"); report=c.report(assess_event(event),"nonfinite"); c.check("invalid value blocks",report["status"],"blocked"); c.check("nonfinite code","NONFINITE_VALUES" in codes(report))
        event=capture(); event.signals[0].timestamps_s[3]=event.signals[0].timestamps_s[2]; report=c.report(assess_event(event),"timestamps"); c.check("invalid times block",report["status"],"blocked"); c.check("timestamp code","INVALID_TIMESTAMPS" in codes(report))

    @r.case("L2-16", "Extreme finite arithmetic and JSON safety", "L2", ["finite_json","overflow_intervals","accurate_bounded_counts"], "deterministic helper")
    def finite(c):
        event=capture([-1e308,-5e307,0,5e307,1e308],times=[-1e308,-5e307,0,5e307,1e308],rate=1e-308); report=c.report(assess_event(event,{"expected_interval_s":1e-308})); c.check("finite JSON",bool(json.dumps(report,allow_nan=False)))
        report=c.report(assess_event(capture([1,2],times=[-1e308,1e308],rate=1),{"expected_interval_s":1}),"overflow_interval"); c.check("unrepresentable duration explicit null",next(x for x in report["issues"] if x["code"]=="RECORDING_GAP")["intervals"][0]["observed_interval_s"],None)
        report=c.report(assess_event(capture(list(range(100))),{"channels":{"voltage":{"max":0}}}),"counts"); issue=next(x for x in report["issues"] if x["code"]=="OUT_OF_BOUNDS"); c.check("99 violations",issue["count"],99); c.check("only 25 details",len(issue["rows"]),25)

    @r.case("L2-17", "Strict quality settings and per-channel cadence override", "L2", ["settings_validation","channel_cadence_override","strict_finite_config"], "deterministic helper")
    def settings(c):
        invalid=[{"typo":1},{"expected_interval_s":0},{"expected_interval_s":True},{"gap_factor":1},{"gap_factor":float("inf")},{"channels":{"v":{"min":2,"max":1}}},{"channels":{"v":{"expected_stable":True}}},{"channels":{"v":{"flatline_samples":True}}},{"required_channels":["v","v"]}]
        for i,value in enumerate(invalid): c.reject(f"invalid setting {i}",lambda v=value:validate_expectations(v))
        report=c.report(assess_event(capture([1,2,3],times=[0,3,4],rate=1),{"expected_interval_s":100,"channels":{"voltage":{"expected_interval_s":1}}})); c.check("channel override detects gap","RECORDING_GAP" in codes(report))

    @r.case("ANALYSIS-01", "RF trip, decay and forward/reflected comparison", "L2", ["rf_trip","cavity_decay","pressure_pre_post","forward_reflected_ratio","rf_plots"], "API TestClient and deterministic domain helper")
    def rf(c):
        times=[i/1000 for i in range(2001)]; values=[1 if t<1 else math.exp(-(t-1)/.1) for t in times]
        event=capture(values,times=times,rate=1000,name="cavity_field",unit="1",domain="rf"); event.event_id="DEMO-RF"
        for name,vals,unit in [("reflected_power",[2]*len(times),"W"),("forward_power",[10]*len(times),"W"),("tuner_pressure",[1 if t<1 else 3 for t in times],"Pa")]: event.signals.append(Signal(name=name,values=vals,timestamps_s=times,sample_rate_hz=1000,unit=unit))
        event.states=[StateEvent(name="RF_INTERLOCK",value="ACTIVE",timestamp_s=1)]
        c.input("rf_trip_event.json",event.model_dump_json(indent=2).encode()); c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-RF/analyze"),key="analysis")
        c.check("RF domain processor",result["processor"],"rf_trip"); features=result["features"]
        c.near("trip time",features["trip_time_s"],1); c.near("1/e decay milliseconds",features["approx_decay_ms"],100,1e-5); c.near("pressure delta",features["pressure_delta"],2)
        comparison=features["forward_reflected_comparison"]; c.near("forward mean",comparison["pre_forward_mean"],10); c.near("reflected mean",comparison["pre_reflected_mean"],2); c.near("reflected/forward ratio",comparison["pre_reflected_to_forward_ratio"],.2)
        mismatched=event.model_copy(deep=True); next(s for s in mismatched.signals if s.name=="forward_power").unit="V"; guarded=ProcessorRegistry().get("rf").process(mismatched)
        c.check("incompatible power ratio withheld",guarded.features["forward_reflected_comparison"]["pre_reflected_to_forward_ratio"],None); c.check("unit mismatch warning",any("units differ" in w for w in guarded.features["warnings"]))
        c.artifact("event",event); c.artifact("analysis",result)
        r.plot_data["rf"]={"series":[{"name":"Cavity field","x":times[::4],"y":values[::4]}],"y_label":"Cavity field (normalized)","annotation":f"Measured trip {features['trip_time_s']:.3f} s; 1/e crossing {features['approx_decay_ms']:.1f} ms later."}

    @r.case("ANALYSIS-02", "X-ray and gradient trends remain descriptive", "L2", ["field_emission_trends","xray_gradient_correlation","scatter_plot","conditioning_limitations"], "API TestClient")
    def emission(c):
        times=[i/10 for i in range(20)]; event=capture([3*t for t in times],times=times,name="xray",unit="counts/s",domain="rf"); event.event_id="DEMO-FE"; event.signals.append(Signal(name="cavity_gradient",unit="MV/m",sample_rate_hz=10,timestamps_s=times,values=[2+t for t in times]))
        c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-FE/analyze"),key="analysis"); c.check("field emission trend processor",result["processor"],"rf_field_emission_trends"); c.near("known linear correlation",result["features"]["xray_gradient_correlation"],1)
        c.check("scatter present",any(p["kind"]=="scatter" for p in result["plot_specs"])); c.check("no causal diagnosis",any("does not establish" in w for w in result["features"]["warnings"])); c.artifact("event",client.get("/events/DEMO-FE").json()); c.artifact("analysis",result)

    @r.case("ANALYSIS-03", "Mechanical RMS and calibrated FFT", "L2", ["mechanical_rms","fft_frequency","fft_amplitude","native_timestamp_rate","fft_plot"], "API TestClient and deterministic helper")
    def mechanical(c):
        import numpy as np
        times=[i/1000 for i in range(2000)]; values=[(.5 if t<1 else 2.5)*math.sin(2*math.pi*40*t) for t in times]
        event=capture(values,times=times,rate=1000,name="vibration",unit="m/s^2",domain="mechanical"); event.event_id="DEMO-MECHANICAL"; event.states=[StateEvent(name="VIBRATION_ALARM",value="ACTIVE",timestamp_s=1)]
        c.input("mechanical_vibration.csv",("time [s],vibration [m/s^2]\n"+"".join(f"{t},{v}\n" for t,v in zip(times,values))).encode()); c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-MECHANICAL/analyze"),key="analysis")
        c.check("mechanical processor",result["processor"],"mechanical_vibration"); features=result["features"]; c.near("40 Hz peak",features["dominant_frequency_hz"],40,1e-7); c.near("pre RMS",features["rms_pre"],.5/math.sqrt(2)); c.near("post RMS",features["rms_post"],2.5/math.sqrt(2))
        frequency,amplitude=fft_spectrum(17+2.5*np.sin(2*np.pi*40*np.arange(2000)/1000),1000); peak=1+int(np.argmax(amplitude[1:])); c.near("coherent amplitude calibration",float(amplitude[peak]),2.5)
        plot=next(p for p in result["plot_specs"] if p["kind"]=="fft"); c.artifact("event",event); c.artifact("analysis",result)
        r.plot_data["mechanical"]={"series":[{"name":"Post-event amplitude spectrum","x":plot["frequencies_hz"],"y":plot["amplitudes"]}],"y_label":"Amplitude (m/s²)","annotation":f"Measured dominant peak {features['dominant_frequency_hz']:.1f} Hz; post RMS {features['rms_post']:.3f} m/s²."}

    @r.case("ANALYSIS-04", "PLC chronology, repeated transitions and incomplete sequences", "L2", ["plc_chronology","transition_intervals","sequence_validation","categorical_timeline"], "API TestClient and deterministic helper")
    def plc(c):
        event=EngineeringEvent(event_id="DEMO-PLC",domain="plc",event_type="presentation_fixture",provenance={"source":"synthetic_presentation_fixture"},states=[StateEvent(timestamp_s=t,name="PLC_STATE",value=v) for t,v in [(5,"INTERLOCKED"),(1,"WARNING"),(0,"RUNNING"),(3,"RUNNING"),(4,"WARNING"),(2,"INTERLOCKED")]])
        c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-PLC/analyze"),key="analysis"); c.check("chronological sequence",result["features"]["sequence"],["RUNNING","WARNING","INTERLOCKED","RUNNING","WARNING","INTERLOCKED"]); c.check("all transition intervals",len(result["features"]["transition_intervals"]),5)
        short=event.model_copy(deep=True); short.states=[StateEvent(timestamp_s=1,name="PLC_STATE",value="INTERLOCKED")]; result_short=ProcessorRegistry().get("plc").process(short); c.check("incomplete sequence flagged",result_short.features["expected_sequence_observed"],False); c.check("no invented states",result_short.features["sequence"],["INTERLOCKED"]); c.artifact("event",event); c.artifact("analysis",result)

    @r.case("ANALYSIS-05", "Common-grid alignment and no-extrapolation provenance", "L2", ["grid_alignment","overlap_only","no_extrapolation","raw_unchanged","downsample_warning","alignment_bound"], "deterministic helper")
    def align(c):
        a=capture([0,2,4,6],times=[0,1,2,3],rate=1,name="a").signals[0]; b=capture([1,2,3,4,5],times=[.5,1,1.5,2,2.5],rate=2,name="b").signals[0]; before=[s.model_dump() for s in (a,b)]
        grid,values,metadata=align_signals([a,b]); c.near("overlap grid",grid.tolist(),[.5,1,1.5,2,2.5]); c.near("linear interpolation",values["a"].tolist(),[1,2,3,4,5]); c.check("source signals unchanged",[s.model_dump() for s in (a,b)],before)
        _,_,down=align_signals([a,b],1); c.check("downsample warning",any("no anti-alias" in w for w in down["warnings"])); c.report(metadata,"alignment")
        far=capture([2,3],times=[4,5],rate=1,name="far").signals[0]; c.reject("nonoverlap rejected",lambda:align_signals([a,far]),"do not overlap")
        c.reject("output million bound",lambda:align_signals([a,b],1e6),"1,000,000")

    @r.case("ANALYSIS-06", "Adapter cleaning records transformations without raw edits", "L2", ["adapter_cleaning","nonfinite_removed","duplicate_times_averaged","stable_sort","cleaning_provenance"], "unvalidated adapter helper (not public ingestion)")
    def cleaning(c):
        raw=Signal.model_construct(name="raw",sample_rate_hz=1.0,unit="V",timestamps_s=[2,1,1,0,3],values=[4,1,3,0,float("nan")],metadata={})
        times,values,metadata=clean_signal(raw); c.near("clean times",times.tolist(),[0,1,2]); c.near("averaged duplicate values",values.tolist(),[0,2,4]); c.check("one removed nonfinite",metadata["removed_nonfinite_samples"],1); c.check("one duplicate averaged",metadata["duplicate_timestamps_averaged"],1); c.check("sorted flag",metadata["reordered"]); c.check("raw order unchanged",raw.timestamps_s,[2,1,1,0,3]); c.report(metadata,"cleaning")
        c.reject("FFT short input",lambda:fft_spectrum([1,2,3],10),"at least four")

    @r.case("ANALYSIS-07", "Gaps, irregular timing and ordinal order withhold spectra", "L2", ["gap_analysis_gate","irregular_analysis_gate","ordinal_analysis_gate","no_gap_interpolation","sample_rate_mismatch_allowed"], "API TestClient")
    def timing_gates(c):
        fixtures=[("GAP",[0,1,2,20,21,22],{}),("IRREGULAR",[0,1,2.4,3.4,4.8,5.8],{}),("ORDINAL",[0,1,2,3,4,5],{"import_summary":{"time_basis":"row_index"}})]
        for suffix,times,metadata in fixtures:
            event=capture([0,1,0,1,0,1],times=times,rate=1,name="vibration",unit="m/s^2",domain="mechanical",metadata=metadata); event.event_id=f"DEMO-GATE-{suffix}"
            c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post(f"/events/{event.event_id}/analyze")); c.check(f"{suffix} descriptive fallback",result["processor"],"mixed_evidence_summary"); c.check(f"{suffix} spectra withheld",not any(p["kind"]=="fft" for p in result["plot_specs"])); c.report(result,suffix)
        event=capture([math.sin(2*math.pi*2*i/100) for i in range(200)],times=[i/100 for i in range(200)],rate=10,name="vibration",unit="m/s^2",domain="mechanical"); event.event_id="DEMO-RATE-AUTHORITY"; c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-RATE-AUTHORITY/analyze")); c.check("rate mismatch still uses real timing",result["processor"],"mechanical_vibration"); c.check("mismatch flag attached","SAMPLE_RATE_MISMATCH" in codes(result["features"]["data_quality"]))

    @r.case("ANALYSIS-08", "Extreme domain values fall back to finite descriptive evidence", "L2", ["NUMERICAL_RANGE","finite_domain_results","overflow_fallback","evidence_retained"], "API TestClient")
    def overflow(c):
        event=capture([1e308 if i%2 else -1e308 for i in range(40)],times=[i/10 for i in range(40)],rate=10,name="vibration",unit="m/s^2",domain="mechanical"); event.event_id="DEMO-RANGE"
        c.response(client.post("/events",json=event.model_dump(mode="json"))); result=c.response(client.post("/events/DEMO-RANGE/analyze"),key="analysis"); c.check("descriptive fallback",result["processor"],"mixed_evidence_summary"); c.check("range warning","NUMERICAL_RANGE" in codes(result["features"]["data_quality"])); c.check("finite JSON",bool(json.dumps(result,allow_nan=False))); c.check("extreme measurement preserved",client.get("/events/DEMO-RANGE").json()["signals"][0]["values"][0],-1e308); c.artifact("analysis",result)

    from l1_l2_demo_generators import demonstrate_generators
    demonstrate_generators(r,client)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=PROJECT.parent.parent / "deliverables" / "L1_L2_Presentation" / "evidence")
    arguments=parser.parse_args(); output=arguments.output.expanduser().resolve(); output.mkdir(parents=True,exist_ok=True)
    runner=Runner(output)
    # This environment is explicitly replaced before services initialize; caches
    # and environment are restored, and only the temporary runtime is removed.
    environment={"FRIB_CONFIG_DIR":str(PROJECT/"config"),"FRIB_LLM_PROVIDER":"mock","FRIB_EMBEDDING_PROVIDER":"hash","FRIB_VECTOR_PROVIDER":"sqlite"}
    with tempfile.TemporaryDirectory(prefix="frib-demo-runtime-",dir=output) as temporary:
        environment["FRIB_DATA_DIR"]=str(Path(temporary)/"data")
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,environment)); get_config.cache_clear(); get_services.cache_clear()
            try:
                state={"services":Services()}; stack.enter_context(patch.object(api,"get_services",lambda:state["services"]))
                with TestClient(api.app) as client: demonstrate(runner,client,state)
            finally: get_config.cache_clear(); get_services.cache_clear()
    return runner.finish()


if __name__=="__main__": raise SystemExit(main())
