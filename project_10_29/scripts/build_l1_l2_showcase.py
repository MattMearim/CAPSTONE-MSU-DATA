#!/usr/bin/env python3
"""Build a portable, offline HTML presentation from recorded demonstration evidence.

Run the scenario runner and pytest first. This generator reports their results;
it never runs the application, invents evidence, or contacts a network service.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET


FOCUSED_MODULES = {
    "test_ingestion", "test_upload_quality", "test_event_quality", "test_quality_api",
    "test_quality_ui", "test_units", "test_preview_limits", "test_mixed_api",
    "test_processing", "test_evidence_processing", "test_processing_robustness", "test_generators",
}


def _relative_url(path: Path, output: Path) -> str:
    return quote(Path(os.path.relpath(path.resolve(), output.parent.resolve())).as_posix(), safe="/.-_")


def _source(path: Path, output: Path) -> dict:
    return {"name": path.name, "url": _relative_url(path, output), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _artifact_path(directory: Path, value: str) -> Path | None:
    """Evidence links must refer to files inside the selected evidence directory."""
    if not isinstance(value, str) or ":" in value or "\\" in value or Path(value).is_absolute():
        return None
    resolved = (directory / value).resolve()
    if not resolved.is_relative_to(directory.resolve()) or not resolved.is_file():
        return None
    return resolved


def _scope(steps: list) -> str:
    explicit = next((str(step).split(":", 1)[1].strip() for step in steps if str(step).lower().startswith("scope:")), None)
    return explicit or "Scope not recorded"


def _compact(value, depth=0):
    if depth > 12:
        return "[Deep detail omitted from this view; see source JSON]"
    if isinstance(value, dict):
        return {str(key): _compact(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        items = [_compact(item, depth + 1) for item in value[:60]]
        if len(value) > 60:
            items.append({"display_note": f"{len(value) - 60} additional entries are available in the source JSON."})
        return items
    if isinstance(value, str) and len(value) > 16000:
        return value[:16000] + "\n[Display abbreviated; see source JSON]"
    return value


def _reports(value, depth=0):
    if depth > 9:
        return []
    if isinstance(value, dict):
        if value.get("stage") in {"L1", "L2"} and isinstance(value.get("issues"), list) and isinstance(value.get("summary"), dict):
            return [value]
        return [report for key, item in value.items() if key not in {"signals", "values", "timestamps_s", "plot_specs"} for report in _reports(item, depth + 1)]
    if isinstance(value, list):
        return [report for item in value[:60] for report in _reports(item, depth + 1)]
    return []


def _series(name, times, values, unit, time_label="Elapsed time (s)", source_count=None, metadata=None):
    if not isinstance(times, list) or not isinstance(values, list):
        return None
    observed = [(float(t), float(v)) for t, v in zip(times, values) if isinstance(t, (int, float)) and isinstance(v, (int, float)) and not isinstance(t, bool) and not isinstance(v, bool) and math.isfinite(t) and math.isfinite(v)]
    if not observed:
        return None
    count = len(observed)
    step = max(1, math.ceil(count / 1400))
    indices = list(range(0, count, step))
    if indices[-1] != count - 1:
        indices.append(count - 1)
    return {"name": str(name), "unit": str(unit or "unit not recorded"), "time_label": time_label,
            "times": [observed[index][0] for index in indices], "values": [observed[index][1] for index in indices],
            "observed_count": source_count or count, "display_count": len(indices), "reduced": len(indices) < count or bool(source_count and source_count > count),
            "metadata": metadata or {}}


def _plot_artifact(path, output):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    channels = []
    result = {"title": path.name, "source": _source(path, output), "channels": channels}
    if isinstance(obj.get("signals"), list):
        metadata = obj.get("metadata", {})
        ordinal = metadata.get("import_summary", {}).get("time_basis") == "row_index"
        time_label = "Record order (not measured time)" if ordinal else "Elapsed time (s)"
        for signal in obj["signals"]:
            if not isinstance(signal, dict):
                continue
            signal_metadata = signal.get("metadata") or {}
            count = signal_metadata.get("preview_total_samples")
            channel = _series(signal.get("name", "Channel"), signal.get("timestamps_s"), signal.get("values"), signal.get("unit"), time_label, source_count=count if isinstance(count, int) else None, metadata=signal_metadata)
            if channel:
                channels.append(channel)
        result.update(kind="event", event_id=obj.get("event_id"), quality=metadata.get("data_quality"),
                      expectations=metadata.get("quality_expectations", {}), states=_compact(obj.get("states", [])[:30]), logs=_compact(obj.get("logs", [])[:30]),
                      state_count=len(obj.get("states", [])), log_count=len(obj.get("logs", [])), ordinal=ordinal)
    elif isinstance(obj.get("plot_specs"), list):
        for spec in obj["plot_specs"]:
            if spec.get("kind") == "timeseries":
                for name, values in spec.get("values", {}).items():
                    channel = _series(spec.get("labels", {}).get(name, name), spec.get("timestamps_s"), values, spec.get("units", {}).get(name), spec.get("time_label") or "Elapsed time (s)")
                    if channel:
                        channels.append(channel)
            elif spec.get("kind") == "fft":
                channel = _series(spec.get("title") or "Frequency spectrum", spec.get("frequencies_hz"), spec.get("amplitudes"), spec.get("amplitude_unit"), "Frequency (Hz)")
                if channel:
                    channels.append(channel)
        result.update(kind="analysis", event_id=obj.get("event_id"), findings=_compact(obj.get("findings", [])), quality=obj.get("features", {}).get("data_quality"), features=_compact(obj.get("features", {})))
    else:
        return None
    return result


def load_evidence(evidence, output):
    selected = Path(evidence).resolve()
    path = selected / "scenario_results.json" if selected.is_dir() else selected
    result = {"available": False, "scenarios": [], "plots": [], "warnings": [], "source": None, "summary": {"total": 0, "passed": 0, "failed": 0, "other": 0}}
    if not path.is_file():
        result["warnings"].append("Scenario results are unavailable. Run scripts/run_l1_l2_demo.py, then rebuild this showcase.")
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("scenarios"), list):
            raise ValueError("Expected a JSON object containing a scenarios list.")
    except (OSError, ValueError) as exc:
        result["warnings"].append(f"Scenario results could not be read: {exc}")
        return result
    result.update(available=True, source=_source(path, output), generated_at=payload.get("generated_at"), schema_version=payload.get("schema_version"), project=payload.get("project"))
    directory = path.parent
    plots_seen = set()
    for index, item in enumerate(payload["scenarios"]):
        if not isinstance(item, dict):
            result["warnings"].append(f"Scenario entry {index + 1} is not an object and could not be displayed.")
            continue
        case = {key: _compact(item.get(key)) for key in ["id", "title", "stage", "features", "status", "expected", "observed", "steps"]}
        case["id"] = str(item.get("id") or f"scenario-{index + 1}")
        case["status"] = str(item.get("status") or "unrecorded")
        case["stage"] = str(item.get("stage") or "stage unrecorded")
        case["title"] = str(item.get("title") or case["id"])
        case["features"] = [str(feature) for feature in item.get("features", [])] if isinstance(item.get("features"), list) else []
        case["steps"] = [str(step) for step in item.get("steps", [])] if isinstance(item.get("steps"), list) else []
        case["scope"] = _scope(case["steps"])
        case["reports"] = _compact(_reports(item.get("observed")))
        case["files"] = []
        for category in ["input_files", "artifacts"]:
            for relative in item.get(category, []) or []:
                artifact = _artifact_path(directory, relative)
                if artifact is None:
                    result["warnings"].append(f"{case['id']}: a missing or unsafe evidence link was excluded ({relative!s}).")
                    continue
                case["files"].append({**_source(artifact, output), "label": str(relative), "category": category})
                if category == "artifacts" and artifact.suffix.lower() == ".json" and artifact not in plots_seen:
                    plot = _plot_artifact(artifact, output)
                    if plot:
                        plot.update(scenario_id=case["id"], scenario_title=case.get("title"))
                        result["plots"].append(plot)
                        plots_seen.add(artifact)
        casefile = _artifact_path(directory, f"cases/{case['id']}.json")
        if casefile:
            case["case_source"] = _source(casefile, output)
        result["scenarios"].append(case)
    counts = Counter(case.get("status") for case in result["scenarios"])
    result["summary"] = {"total": len(result["scenarios"]), "passed": counts["passed"], "failed": counts["failed"], "other": sum(count for status, count in counts.items() if status not in {"passed", "failed"})}
    declared = payload.get("summary", {})
    if any(declared.get(key) != result["summary"][key] for key in ["total", "passed", "failed"]):
        result["warnings"].append("The runner summary differs from the scenario records. Displayed counts were recomputed from the recorded statuses.")
    return result


def load_junit(path, output):
    result = {"available": False, "source": None, "tests": [], "modules": [], "warning": None, "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "focused": 0}}
    if path is None or not Path(path).is_file():
        result["warning"] = "Full-suite JUnit XML is unavailable. Test counts are not inferred from the demonstrations."
        return result
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        result["warning"] = f"JUnit XML could not be read: {exc}"
        return result
    result.update(available=True, source=_source(path, output))
    modules = {}
    for case in root.iter("testcase"):
        classname = case.get("classname", "unrecorded")
        module = next((part for part in classname.split(".") if part.startswith("test_")), classname)
        failed = case.find("failure") is not None or case.find("error") is not None
        status = "failed" if failed else "skipped" if case.find("skipped") is not None else "passed"
        focused = module in FOCUSED_MODULES
        scope = "Automated UI · L1/L2" if module == "test_quality_ui" else "Automated UI · multiple levels" if module == "test_dashboard_ui" else "API test" if "api" in module else "Helper / processor test" if focused else "Project test · scope varies"
        detail = case.find("failure") if case.find("failure") is not None else case.find("error")
        result["tests"].append({"name": case.get("name", "Unnamed test"), "module": module, "classname": classname, "status": status,
                                "seconds": case.get("time"), "focused": focused, "scope": scope, "detail": (detail.text or "")[:10000] if detail is not None else None})
        row = modules.setdefault(module, {"name": module, "total": 0, "passed": 0, "failed": 0, "skipped": 0, "focused": focused, "scope": scope})
        row["total"] += 1
        row[status] += 1
    result["modules"] = sorted(modules.values(), key=lambda row: (not row["focused"], row["name"]))
    counts = Counter(test["status"] for test in result["tests"])
    result["summary"] = {"total": len(result["tests"]), "passed": counts["passed"], "failed": counts["failed"], "skipped": counts["skipped"], "focused": sum(test["focused"] for test in result["tests"])}
    return result


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRIB · L1 / L2 Evidence Showcase</title>
<style>
:root{--paper:#faf9f6;--card:#fff;--ink:#142a3c;--muted:#627384;--teal:#087f82;--tealsoft:#e5f3f1;--amber:#a96710;--ambersoft:#fff3d9;--red:#ae3939;--line:#dce4e8;--navy:#102d42;--shadow:0 12px 40px #12344c09}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select{font:inherit}button,a,input,select{outline-offset:4px}a{color:var(--teal);text-underline-offset:3px}button{cursor:pointer;border:1px solid var(--line);border-radius:10px;padding:.6rem .95rem;background:white;color:var(--ink)}button:hover{border-color:var(--teal);background:var(--tealsoft)}button.primary{background:var(--teal);border-color:var(--teal);color:white}button.primary:hover{background:#096b6e}button:disabled{opacity:.45;cursor:default}input,select{border:1px solid #bdccd3;border-radius:9px;padding:.6rem .75rem;background:white;color:var(--ink);max-width:100%}.topbar{position:sticky;top:0;z-index:30;background:#faf9f6f2;backdrop-filter:blur(12px);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 2rem}.brand{font-weight:800;letter-spacing:.05em;font-size:13px;display:flex;align-items:center;gap:.7rem}.brandmark{background:var(--navy);color:white;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-size:18px}.top-actions{display:flex;gap:.55rem;align-items:center}.offline{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--teal)}.shell{display:grid;grid-template-columns:230px minmax(0,1fr);max-width:1550px;margin:auto}.rail{position:sticky;top:85px;height:calc(100vh - 110px);overflow:auto;padding:2rem 1.4rem}.rail p{font-size:10px;font-weight:800;letter-spacing:.15em;color:var(--muted);text-transform:uppercase}.rail a{display:flex;gap:.7rem;text-decoration:none;color:var(--muted);font-size:12px;padding:.6rem;border-radius:8px;align-items:center}.rail a:hover,.rail a.active{color:var(--ink);background:white;box-shadow:var(--shadow)}.rail a span{font-variant-numeric:tabular-nums;font-size:10px;color:var(--teal)}main{min-width:0;padding:0 2rem 5rem}.section{padding:3.5rem 0;border-bottom:1px solid var(--line);scroll-margin-top:95px}.eyebrow{font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--teal);margin-bottom:.8rem}h1,h2,h3,p{margin-top:0}h1{font-size:clamp(40px,5.1vw,70px);line-height:1.06;letter-spacing:-.055em;max-width:820px;margin-bottom:1.25rem}h2{font-size:clamp(28px,3vw,42px);line-height:1.15;letter-spacing:-.035em;margin-bottom:1rem}h3{font-size:18px;line-height:1.3;margin-bottom:.6rem}.lead{font-size:19px;line-height:1.6;color:var(--muted);max-width:850px}.small,.muted{color:var(--muted)}.small{font-size:12px}.hero-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:2rem;align-items:center}.orb{background:var(--navy);color:white;border-radius:24px;padding:2rem;position:relative;overflow:hidden;box-shadow:0 22px 50px #12344c18}.orb:after{content:"";position:absolute;width:220px;height:220px;border:1px solid #ffffff15;border-radius:50%;right:-70px;top:-90px}.orb h3{font-size:30px;letter-spacing:-.03em}.orb .small{color:#b5cbd4}.flow{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin:1.5rem 0}.flow-cell{border:1px solid #ffffff25;border-radius:12px;padding:.9rem 1rem;flex:1;min-width:125px}.flow-cell strong{display:block;font-size:23px}.flow-cell span{font-size:11px;color:#c4dadd}.human{color:#a7e5db;border-top:1px solid #ffffff22;padding-top:1rem;font-size:12px}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;margin:2rem 0}.stat,.card{border:1px solid var(--line);border-radius:16px;background:var(--card);padding:1.4rem;box-shadow:var(--shadow)}.stat strong{font-size:32px;line-height:1.2;display:block;letter-spacing:-.04em}.stat span{font-size:12px;color:var(--muted)}.stat .tiny{display:block;font-size:10px;color:var(--muted);margin-top:.6rem}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.number{font-size:11px;font-weight:800;color:var(--teal);letter-spacing:.12em;margin-bottom:.6rem}.card p:last-child{margin-bottom:0}.callout{border:1px solid #d6e9e4;background:var(--tealsoft);padding:1rem 1.2rem;border-radius:12px;margin:1rem 0}.callout.warning{background:var(--ambersoft);border-color:#ead5a8;color:#714a13}.callout.error{background:#fdeeee;border-color:#f0c2c2;color:var(--red)}.badges{display:flex;flex-wrap:wrap;gap:.4rem;margin:.75rem 0}.badge{border-radius:99px;padding:.18rem .6rem;background:#eff3f5;font-size:10px;font-weight:700;color:#4d6474;line-height:1.8}.badge.pass{color:#0a6b62;background:#e4f5ed}.badge.fail{color:#a22d2d;background:#fce7e7}.badge.unknown{color:#8c631b;background:var(--ambersoft)}.badge.stage{background:#e7eef6;color:#285777}.toolbar{display:flex;flex-wrap:wrap;gap:.65rem;margin:1.2rem 0}.toolbar input{flex:1;min-width:180px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:white}table{border-collapse:collapse;width:100%;text-align:left;font-size:12px}th,td{padding:.85rem 1rem;border-bottom:1px solid #e9edef;vertical-align:top}th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;background:#f7f9fa}tr:last-child td{border-bottom:0}td strong{font-size:12px}.case{background:white;border:1px solid var(--line);border-radius:13px;margin:.8rem 0;overflow:hidden}.case summary{padding:1rem 1.15rem;cursor:pointer;list-style:none;display:flex;justify-content:space-between;gap:1rem;align-items:center}.case summary::-webkit-details-marker{display:none}.case summary h3{font-size:15px;margin:0}.case summary .small{font-size:10px}.case[open] summary{border-bottom:1px solid var(--line)}.case-body{padding:1.2rem}.case pre,.code{font:11px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f8;border:1px solid #e5ebee;border-radius:9px;padding:1rem;max-height:330px;overflow:auto}.case .grid2 h4{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:0 0 .4rem}.filelinks{display:flex;gap:.7rem;flex-wrap:wrap;font-size:11px;margin-top:.8rem}.steps{padding-left:1.3rem;font-size:12px}.source{font-size:10px;color:var(--muted);word-break:break-all}.plot-panel{border:1px solid var(--line);background:white;padding:1.2rem;border-radius:15px;margin:1rem 0}.plot-title{display:flex;justify-content:space-between;gap:1rem;align-items:center}.plot-title h3{font-size:14px;margin:0}.plot-panel svg{width:100%;height:auto;display:block}.plot-axis{font-size:11px;fill:#667d8b}.plot-line{fill:none;stroke:var(--teal);stroke-width:1.7}.plot-grid{stroke:#e9eef0;stroke-width:1}.caption{font-size:11px;color:var(--muted);margin-top:.4rem}.legend-row{display:flex;gap:1rem;align-items:center;font-size:11px;color:var(--muted)}.dot{width:7px;height:7px;border-radius:50%;background:var(--teal);display:inline-block;margin-right:.3rem}.report-bar{display:flex;height:12px;border-radius:99px;overflow:hidden;background:#eef2f4;margin:1rem 0}.report-bar span{min-width:0}.commands .code{max-height:none;margin-bottom:.5rem}.foot{font-size:11px;color:var(--muted);padding-top:1rem}.present-nav{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:50;display:none;align-items:center;gap:.7rem;padding:.55rem .7rem;background:#102d42;color:white;border:1px solid #ffffff2a;border-radius:14px;box-shadow:0 8px 30px #102d4230}.present-nav button{font-size:12px;padding:.35rem .7rem;color:white;background:#ffffff12;border-color:#ffffff30}.present-nav span{white-space:nowrap;font-size:11px;padding:0 .4rem}.presentation .rail{display:none}.presentation .shell{display:block;max-width:1300px}.presentation main{padding-bottom:90px}.presentation .section{min-height:calc(100vh - 85px);border:0;padding:3rem 0}.presentation .section:not(.selected){display:none}.presentation .present-nav{display:flex}.presentation .reveal:not(.revealed){visibility:hidden;opacity:0;transform:translateY(8px)}.reveal{transition:opacity .3s,transform .3s}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;background:white;padding:1rem;z-index:60}.empty{border:1px dashed #becdd5;border-radius:12px;padding:2rem;color:var(--muted);background:#fff;max-width:100%}.statusline{font-size:11px;margin:.7rem 0}.test-detail{font-size:11px;white-space:pre-wrap;background:#fff2f1;border-radius:8px;padding:1rem}.print-only{display:none}@media(max-width:1050px){.rail{display:none}.shell{display:block}.hero-grid{grid-template-columns:1fr}.orb{max-width:680px}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.topbar{padding:.7rem 1rem}.offline{display:none}main{padding:0 1rem 4rem}.section{padding:2rem 0}.grid2,.grid3{grid-template-columns:1fr}.stats{gap:.6rem}.stat{padding:1rem}.top-actions button{font-size:11px;padding:.5rem}.present-nav{bottom:8px;max-width:calc(100% - 16px)}.present-nav span{font-size:9px}.plot-title{display:block}.case summary{align-items:flex-start}.lead{font-size:16px}}@media print{.topbar,.rail,.present-nav,button,.toolbar{display:none!important}.shell{display:block}main{padding:0}.section,.presentation .section{display:block!important;min-height:0;page-break-before:always}.section:first-child{page-break-before:auto}.reveal{visibility:visible!important;opacity:1!important}.case-body{display:block}.stats{grid-template-columns:repeat(4,1fr)}body{background:white}a{color:inherit}}
</style></head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="topbar"><div class="brand"><span class="brandmark">F</span> FRIB <span class="muted">/</span> EVIDENCE SHOWCASE</div><div class="top-actions"><span class="offline">OFFLINE · REAL RESULTS</span><button id="present">Start presentation</button><button id="download-data" title="Download the embedded display data">Download data</button></div></header>
<div class="shell"><aside class="rail" aria-label="Presentation sections"><p>Guided walkthrough</p><nav id="nav"></nav><p style="margin-top:2rem">12 sections · ~12–15 min</p><div class="small">Use ← / → to navigate.<br>In presentation mode, Space reveals the next item.</div></aside>
<main id="main">
<section class="section selected" id="s1" data-title="The evidence"><div class="eyebrow">01 / A demonstrable foundation</div><div class="hero-grid"><div><h1>Evidence first.<br>Engineering with context.</h1><p class="lead">A working demonstration of Level 1 acquisition and Level 2 quality, processing and visualization—backed by recorded scenarios and automated tests.</p><div class="badges"><span class="badge stage">L1 · Preserve and review</span><span class="badge stage">L2 · Check and explain</span><span class="badge">Human supervised</span></div></div><div class="orb reveal"><div class="number" style="color:#a7e5db">FOUR-LEVEL ARCHITECTURE</div><h3>Keep the chain of evidence visible.</h3><div class="flow"><div class="flow-cell"><strong>L1</strong><span>Original operational evidence</span></div><span>→</span><div class="flow-cell"><strong>L2</strong><span>Engineering-ready views</span></div></div><div class="human">L3 document context → L4 human-reviewed knowledge<br>This showcase concentrates on L1 and L2.</div></div></div><div id="hero-stats" class="stats reveal"></div><div id="availability"></div><p class="small" id="evidence-date"></p></section>
<section class="section" id="s2" data-title="The operating model"><div class="eyebrow">02 / What the system does</div><h2>A supervised evidence workflow.</h2><p class="lead">Capture the source, inspect its limitations, make any repair choice explicit, then derive views that remain traceable to the original.</p><div class="grid3"><article class="card reveal"><div class="number">01 · SOURCE</div><h3>Preserve before interpreting</h3><p>Original files, provenance and checksums remain available. A reviewed copy is identified separately when a repair is selected.</p></article><article class="card reveal"><div class="number">02 · REVIEW</div><h3>Expose uncertainty</h3><p>Malformed rows, units, timing, missing entries and declared expectations become reviewable findings.</p></article><article class="card reveal"><div class="number">03 · DERIVE</div><h3>Explain the result</h3><p>Numeric signals, categories, text and processing outputs keep their labels, units and scope.</p></article></div><div class="callout reveal">These descriptions are demonstrated only where the recorded cases below show supporting evidence. The application does not control FRIB equipment or establish a physical cause from a quality flag.</div><div id="scope-summary" class="badges"></div></section>
<section class="section" id="s3" data-title="Feature coverage"><div class="eyebrow">03 / Search the recorded coverage</div><h2>Every case has an expected result.</h2><p class="lead">Filter the actual runner output. A failed or unclassified result remains visible; counts are computed from individual scenario records.</p><div class="toolbar"><input id="case-search" type="search" aria-label="Search scenarios" placeholder="Search a feature, scenario, channel or error"><select id="case-stage" aria-label="Filter stage"><option value="">All stages</option></select><select id="case-status" aria-label="Filter status"><option value="">All statuses</option><option>passed</option><option>failed</option><option value="other">other / unknown</option></select></div><div id="case-count" class="statusline"></div><div id="cases"></div><details class="card" style="margin-top:1rem"><summary><strong>Complete recorded feature matrix</strong></summary><div id="feature-matrix" style="margin-top:1rem"></div></details></section>
<section class="section" id="s4" data-title="Source and provenance"><div class="eyebrow">04 / Level 1</div><h2>The original is the reference.</h2><p class="lead">Open the source files beside the expected and observed results. API, helper and UI evidence are labeled separately.</p><div class="grid2"><article class="card reveal"><h3>Live application route</h3><p>Create Dataset → Import CSV / mixed data or Import text / PDF. Inspect the original-file quality report before saving.</p><p class="small">The standalone showcase displays recorded evidence; it is not a screenshot of a running application.</p></article><article class="card reveal"><h3>Provenance distinction</h3><p>An original source attachment preserves uploaded bytes. Event JSON is a parsed view and can incorporate explicitly reviewed repairs.</p><p class="small">Source checksums and receipts are visible in the recorded case details where supplied.</p></article></div><div id="source-cases"></div></section>
<section class="section" id="s5" data-title="Explicit repairs"><div class="eyebrow">05 / Level 1 · No silent repair</div><h2>Review the problem.<br>Choose the change.</h2><div class="grid3"><article class="card reveal"><h3>1. Detect</h3><p>Review bounded source locations and the full affected-entry count.</p></article><article class="card reveal"><h3>2. Select</h3><p>Choose a declared repair and explicit rows when required. Unit hints do not assign physical units.</p></article><article class="card reveal"><h3>3. Recheck</h3><p>Repreview the reviewed copy, retain the original report and inspect the receipt.</p></article></div><div id="repair-cases"></div><div class="callout warning reveal">Original-file rows, reviewed-copy rows and accepted channel sample positions are different coordinates. The report and receipt identify which basis applies.</div></section>
<section class="section" id="s6" data-title="Units and signals"><div class="eyebrow">06 / Level 1 → Level 2</div><h2>Make quantities comparable.</h2><p class="lead">The plots below come from recorded event artifacts. Each channel has its own unit axis. Reduced data is shown as observed points.</p><div id="units-cases"></div><div class="toolbar"><select id="event-plot-select" aria-label="Choose recorded event plot"></select></div><div id="event-plots"></div><div class="callout reveal">Physical unit suggestions need confirmation from the source. Temperature readings use offsets; temperature tolerances describe differences. Original source labels remain available in the evidence files.</div></section>
<section class="section" id="s7" data-title="Categories and text"><div class="eyebrow">07 / More than numeric data</div><h2>Keep states and notes in the picture.</h2><p class="lead">Recorded categories and text remain evidence in their own right. A descriptive summary is not a diagnostic AI conclusion.</p><div id="mixed-cases"></div><div id="narrative-data"></div></section>
<section class="section" id="s8" data-title="Quality expectations"><div class="eyebrow">08 / Level 2</div><h2>Declare what the capture should contain.</h2><div class="grid3"><article class="card reveal"><h3>Sampling</h3><p>Expected interval, estimated cadence and gap checks describe recording consistency.</p></article><article class="card reveal"><h3>Operating expectations</h3><p>Bounds and stability tolerance use stored units; required channels describe intended capture scope.</p></article><article class="card reveal"><h3>Review, not blame</h3><p>A constant signal, abrupt change or unusual value may be a real event. Flags do not establish corruption or negligence.</p></article></div><div id="quality-cases"></div><div class="toolbar"><select id="report-select" aria-label="Choose quality report"></select></div><div id="quality-report"></div></section>
<section class="section" id="s9" data-title="Timing and gaps"><div class="eyebrow">09 / Level 2 · Temporal honesty</div><h2>A line must not invent continuity.</h2><p class="lead">Full captures break at every cadence gap, even when a report lists only bounded examples. Reduced previews use markers. Record order is labeled separately from measured seconds.</p><div id="timing-cases"></div><div class="toolbar"><select id="gap-plot-select" aria-label="Choose timing evidence"></select></div><div id="gap-plots"></div></section>
<section class="section" id="s10" data-title="Processing outputs"><div class="eyebrow">10 / Level 2 · Derived evidence</div><h2>Inspect the engineering-ready view.</h2><p class="lead">These figures use numeric values from recorded analysis artifacts. Each figure links to its original JSON and names its axes and units.</p><div id="processing-cases"></div><div class="toolbar"><select id="analysis-plot-select" aria-label="Choose recorded analysis"></select></div><div id="analysis-plots"></div></section>
<section class="section" id="s11" data-title="Automated verification"><div class="eyebrow">11 / What the test evidence establishes</div><h2>Separate demonstrations from tests.</h2><p class="lead">The JUnit record covers the whole project, including all four architecture levels. The focused subset below is identified by named L1/L2 test modules.</p><div id="test-stats" class="stats"></div><div class="callout reveal">Streamlit AppTest checks automated UI behavior. It does not establish a visual review in a real browser. Helper tests and API demonstrations also have different scopes.</div><div class="toolbar"><input id="test-search" type="search" aria-label="Search tests" placeholder="Search a test name, module or failure"><select id="test-filter" aria-label="Filter test scope"><option value="all">Whole project suite</option><option value="focused">L1/L2 related modules</option><option value="failed">Failures / errors</option><option value="ui">Automated UI modules</option></select></div><div id="module-table"></div><div id="test-results"></div><div id="junit-source" class="source"></div></section>
<section class="section" id="s12" data-title="Present and reproduce"><div class="eyebrow">12 / From walkthrough to reproducible evidence</div><h2>Run it. Inspect it. Explain its limits.</h2><div class="grid2"><article class="card reveal"><h3>A 12–15 minute route</h3><ol class="steps"><li>Start with the result counts and the evidence scope.</li><li>Show one source-file issue and an explicit repair receipt.</li><li>Compare units, numeric signals, states and text.</li><li>Declare expectations, then inspect timing and processing.</li><li>Close with test evidence, limitations and source downloads.</li></ol></article><article class="card reveal"><h3>Scope of this proof</h3><p>These cases establish the recorded prototype behaviors for their supplied inputs. They do not establish FRIB operational readiness, calibrated physical thresholds, live EPICS integration or sponsor acceptance.</p><p class="small">Run the live application with Start FRIB.cmd. This HTML is a portable evidence presentation and works without a server.</p></article></div><div class="commands"><h3 style="margin-top:1.5rem">Rebuild from the project folder</h3><div class="code" id="cmd-run">.\.venv\Scripts\python.exe scripts\run_l1_l2_demo.py --output &lt;evidence-folder&gt;</div><button data-copy="cmd-run">Copy scenario command</button><div class="code" id="cmd-tests">.\.venv\Scripts\python.exe -m pytest -q --junitxml=&lt;evidence-folder&gt;\pytest-results.xml</div><button data-copy="cmd-tests">Copy test command</button><div class="code" id="cmd-build">.\.venv\Scripts\python.exe scripts\build_l1_l2_showcase.py --evidence &lt;evidence-folder&gt; --junit &lt;evidence-folder&gt;\pytest-results.xml --output &lt;presentation-folder&gt;\Feature_Showcase.html</div><button data-copy="cmd-build">Copy showcase command</button><p id="copy-status" class="small" role="status"></p></div><div id="all-sources" class="card" style="margin-top:1.5rem"></div><p class="foot">Offline HTML · no external scripts, fonts, trackers or services · figures use observed artifact data · source evidence remains separate and inspectable.</p></section>
</main></div><div class="present-nav" aria-label="Presentation navigation"><button id="previous">← Back</button><span id="position"></span><button id="next">Reveal / Next →</button><button id="exit">Exit</button></div>
<script id="showcase-data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById('showcase-data').textContent), E=DATA.evidence, J=DATA.junit;
const $=id=>document.getElementById(id);
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;}
function empty(parent,message){parent.replaceChildren(el('div','empty',message));}
function badge(text,kind){return el('span','badge '+(kind||''),text);}
function link(source,label,download){const a=el('a','',label||source.name);a.href=source.url;if(download)a.download=source.name;return a;}
function stat(value,label,note){const n=el('div','stat');n.append(el('strong','',value),el('span','',label));if(note)n.append(el('span','tiny',note));return n;}
function json(value){return JSON.stringify(value===undefined?null:value,null,2);}
function caseCard(c){const box=el('details','case'),head=el('summary'),title=el('div');title.append(el('h3','',c.title||c.id),el('div','small',c.id+' · '+c.scope));head.append(title,badge(c.status||'unrecorded',c.status==='passed'?'pass':c.status==='failed'?'fail':'unknown'));box.append(head);const body=el('div','case-body'),tags=el('div','badges');tags.append(badge(c.stage||'stage unrecorded','stage'));(c.features||[]).forEach(f=>tags.append(badge(f)));body.append(tags);const compare=el('div','grid2');[['Expected',c.expected],['Observed',c.observed]].forEach(([name,value])=>{const p=el('div');p.append(el('h4','',name),el('pre','',json(value)));compare.append(p);});body.append(compare);const steps=el('ol','steps');c.steps.forEach(step=>steps.append(el('li','',step)));body.append(steps);const files=el('div','filelinks');if(c.case_source)files.append(link(c.case_source,'Case JSON',true));c.files.forEach(file=>files.append(link(file,file.label,true)));body.append(files,el('div','caption','Large arrays may be abbreviated in this display. Download the source evidence for complete values.'));box.append(body);return box;}
function fillCases(id,pattern,limit=4){const node=$(id),cases=E.scenarios.filter(c=>pattern.test([c.id,c.title,c.stage,...c.features].join(' ')));node.replaceChildren();if(!cases.length){empty(node,'No matching scenario was recorded in the selected evidence run.');return;}cases.slice(0,limit).forEach(c=>node.append(caseCard(c)));if(cases.length>limit)node.append(el('p','small',(cases.length-limit)+' more matching cases are searchable in Feature coverage.'));}
function renderCases(){const query=$('case-search').value.toLowerCase().trim(),stage=$('case-stage').value,status=$('case-status').value;const cases=E.scenarios.filter(c=>(!stage||c.stage===stage)&&(!status||(status==='other'?!['passed','failed'].includes(c.status):c.status===status))&&(!query||json(c).toLowerCase().includes(query)));$('case-count').textContent=cases.length+' of '+E.scenarios.length+' recorded scenarios';$('cases').replaceChildren(...cases.map(caseCard));if(!cases.length)empty($('cases'),'No recorded scenarios match these filters.');}
function table(columns,rows){const wrap=el('div','table-wrap'),t=el('table'),head=el('thead'),hr=el('tr');columns.forEach(c=>hr.append(el('th','',c)));head.append(hr);t.append(head);const body=el('tbody');rows.forEach(row=>{const tr=el('tr');row.forEach(value=>{const td=el('td');if(value instanceof Node)td.append(value);else td.textContent=String(value);tr.append(td);});body.append(tr);});t.append(body);wrap.append(t);return wrap;}
function fillFeatureMatrix(){const map=new Map();E.scenarios.forEach(c=>c.features.forEach(f=>{if(!map.has(f))map.set(f,[]);map.get(f).push(c);}));const rows=[...map.entries()].sort((a,b)=>a[0].localeCompare(b[0])).map(([f,cases])=>[f,cases.length,cases.filter(c=>c.status==='passed').length,cases.filter(c=>c.status==='failed').length,[...new Set(cases.map(c=>c.scope))].join('; '),cases.map(c=>c.id).join(', ')]);if(rows.length)$('feature-matrix').append(table(['Recorded feature','Cases','Passed','Failed','Evidence scope','Case IDs'],rows));else empty($('feature-matrix'),'The runner recorded no feature labels.');}
function fmt(v){if(v===0)return '0';const a=Math.abs(v);return a>=100000||a<.001?Number(v).toExponential(2):Number(Number(v).toPrecision(4)).toString();}
function median(values){const a=values.filter(v=>Number.isFinite(v)&&v>0).sort((x,y)=>x-y),m=Math.floor(a.length/2);return a.length?(a.length%2?a[m]:a[m-1]/2+a[m]/2):null;}
function svgElement(tag,attrs,text){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs||{}).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text!==undefined)node.textContent=text;return node;}
function drawSeries(channel,artifact){const panel=el('article','plot-panel'),header=el('div','plot-title');header.append(el('h3','',channel.name+' · '+channel.unit),link(artifact.source,'Source JSON',true));panel.append(header);const times=channel.times,values=channel.values;if(!times.length){empty(panel,'No finite numeric observations were recorded.');return panel;}const w=940,h=280,L=92,R=22,T=20,B=55,xmin=Math.min(...times),xmax=Math.max(...times),ymin=Math.min(...values),ymax=Math.max(...values),yp=ymax===ymin?Math.max(Math.abs(ymin)*.05,1):(ymax-ymin)*.07,lo=ymin-yp,hi=ymax+yp;const sx=x=>L+(x-xmin)/(xmax-xmin||1)*(w-L-R),sy=y=>T+(hi-y)/(hi-lo||1)*(h-T-B);const svg=svgElement('svg',{viewBox:'0 0 '+w+' '+h,role:'img','aria-label':channel.name+'; '+channel.time_label+'; '+channel.unit});for(let i=0;i<=4;i++){const xv=xmin+(xmax-xmin)*i/4,yv=lo+(hi-lo)*i/4;svg.append(svgElement('line',{x1:L,y1:sy(yv),x2:w-R,y2:sy(yv),class:'plot-grid'}),svgElement('text',{x:L-10,y:sy(yv)+4,'text-anchor':'end',class:'plot-axis'},fmt(yv)),svgElement('text',{x:sx(xv),y:h-B+22,'text-anchor':'middle',class:'plot-axis'},fmt(xv)));}svg.append(svgElement('text',{x:(L+w-R)/2,y:h-8,'text-anchor':'middle',class:'plot-axis'},channel.time_label),svgElement('text',{transform:'translate(17 '+((T+h-B)/2)+') rotate(-90)','text-anchor':'middle',class:'plot-axis'},channel.name+' ('+channel.unit+')'));const ordinal=/record order|row order/i.test(channel.time_label)||channel.metadata.inferred_time===true;const settings=(artifact.quality||{}).expectations||artifact.expectations||{},rule=(settings.channels||{})[channel.name]||{},expected=rule.expected_interval_s||settings.expected_interval_s,dt=times.slice(1).map((v,i)=>v-times[i]),ref=expected||median(dt),threshold=expected?1.5:(settings.gap_factor||1.8);const intervals=((artifact.quality||{}).issues||[]).filter(issue=>issue.column===channel.name).flatMap(issue=>issue.intervals||[]);intervals.forEach(g=>{if(Number.isFinite(g.start_s)&&Number.isFinite(g.end_s))svg.append(svgElement('rect',{x:sx(Math.max(xmin,g.start_s)),y:T,width:Math.max(0,sx(Math.min(xmax,g.end_s))-sx(Math.max(xmin,g.start_s))),height:h-T-B,fill:'#fff0cb'}));});if(channel.reduced){times.forEach((t,i)=>svg.append(svgElement('circle',{cx:sx(t),cy:sy(values[i]),r:2.2,fill:'#087f82'})));}else{let path='';times.forEach((t,i)=>{const gap=i&&!ordinal&&!/frequency/i.test(channel.time_label)&&ref&&((t-times[i-1])/ref>=threshold);path+=(i&&!gap?' L':' M')+sx(t).toFixed(2)+' '+sy(values[i]).toFixed(2);});svg.append(svgElement('path',{d:path,class:'plot-line'}));}panel.append(svg);panel.append(el('div','caption',channel.display_count+' displayed observations / '+channel.observed_count+' recorded observations. '+(channel.reduced?'Reduced view: markers only; no continuity is implied.':'Full artifact series; lines break at cadence gaps. ')+(ordinal?'Coordinates are record order, not measured elapsed time.':'')));return panel;}
function setupPlot(selectId,targetId,kind,preferGap){const list=E.plots.filter(p=>p.kind===kind&&p.channels.length);if(preferGap)list.sort((a,b)=>Number(/gap|timing|cadence/i.test(b.scenario_id+' '+b.scenario_title))-Number(/gap|timing|cadence/i.test(a.scenario_id+' '+a.scenario_title)));const select=$(selectId),target=$(targetId);if(!list.length){select.hidden=true;empty(target,'No numeric '+kind+' artifact was available in the recorded evidence. No example data has been substituted.');return;}list.forEach((p,i)=>{const o=el('option','',p.scenario_id+' · '+(p.scenario_title||p.title));o.value=String(i);select.append(o);});function render(){const artifact=list[Number(select.value)||0];target.replaceChildren();artifact.channels.slice(0,8).forEach(c=>target.append(drawSeries(c,artifact)));if(artifact.channels.length>8)target.append(el('p','small','First eight channels shown. Download the source JSON for all channels.'));if(artifact.findings)target.append(el('pre','code',json(artifact.findings)));}select.addEventListener('change',render);render();}
function narrative(){const candidates=E.plots.filter(p=>p.kind==='event'&&(p.state_count||p.log_count));const node=$('narrative-data');if(!candidates.length){empty(node,'No event artifact with categorical or text evidence was recorded.');return;}const item=candidates[0];node.append(el('h3','',item.scenario_id+' · recorded categories and text'),el('p','small',item.state_count+' state entries · '+item.log_count+' log entries · first 30 of each shown'));if(item.states.length)node.append(table(['Coordinate','Channel','Recorded category'],item.states.map(s=>[s.timestamp_s,s.name,json(s.value)])));if(item.logs.length)node.append(table(['Coordinate','Severity','Source text'],item.logs.map(s=>[s.timestamp_s,s.level,s.message])));node.append(link(item.source,'Download the complete event JSON',true));}
function setupReports(){const list=E.scenarios.flatMap(c=>(c.reports||[]).map((r,i)=>({report:r,label:c.id+' · '+r.stage+' · report '+(i+1)})));E.plots.filter(p=>p.quality).forEach(p=>list.push({report:p.quality,label:p.scenario_id+' · artifact quality'}));const select=$('report-select'),node=$('quality-report');if(!list.length){select.hidden=true;empty(node,'No quality report body was included in this evidence run. See the scenario results for recorded expectations and observations.');return;}list.forEach((item,i)=>{const o=el('option','',item.label);o.value=String(i);select.append(o);});function render(){const r=list[Number(select.value)||0].report;node.replaceChildren();const card=el('article','card');card.append(el('h3','',r.stage+' · '+r.status));const stats=el('div','stats');['error','warning','info'].forEach(key=>stats.append(stat((r.summary||{})[key]||0,key+' issue types','Counts describe checks, not physical causes.')));card.append(stats);(r.issues||[]).slice(0,25).forEach(issue=>{const box=el('div','callout '+(issue.severity==='error'?'error':issue.severity==='warning'?'warning':''));box.append(el('strong','',issue.title||issue.code),el('div','',issue.message),el('div','caption','Channel: '+(issue.column||'capture')+' · affected: '+issue.count+' · '+(r.location_basis||'location basis not recorded')+' · example rows: '+(issue.rows||[]).join(', ')));if(issue.suggestion)box.append(el('div','small','Review: '+issue.suggestion));card.append(box);});card.append(el('div','caption','Issue locations are bounded examples. Recorded counts cover the full check; source JSON retains the report.'));node.append(card);}select.addEventListener('change',render);render();}
function renderTests(){const query=$('test-search').value.toLowerCase().trim(),filter=$('test-filter').value;const tests=J.tests.filter(t=>(filter!=='focused'||t.focused)&&(filter!=='failed'||t.status==='failed')&&(filter!=='ui'||t.scope.startsWith('Automated UI'))&&(!query||json(t).toLowerCase().includes(query)));const modules=J.modules.filter(m=>tests.some(t=>t.module===m.name));$('module-table').replaceChildren();if(modules.length)$('module-table').append(table(['Module / declared subset','Scope','Total','Passed','Failed','Skipped'],modules.map(m=>[m.name+(m.focused?' · L1/L2 related':''),m.scope,m.total,m.passed,m.failed,m.skipped])));$('test-results').replaceChildren();$('test-results').append(el('p','small',tests.length+' matching tests; first '+Math.min(tests.length,80)+' test names shown. Module counts describe the complete module.'));tests.slice(0,80).forEach(t=>{const row=el('details','case'),summary=el('summary');summary.append(el('span','small',t.module+' · '+t.name),badge(t.status,t.status==='passed'?'pass':t.status==='failed'?'fail':'unknown'));row.append(summary);const body=el('div','case-body');body.append(el('div','small',t.scope+' · elapsed seconds: '+(t.seconds||'unrecorded')));if(t.detail)body.append(el('pre','test-detail',t.detail));row.append(body);$('test-results').append(row);});if(!J.available)empty($('test-results'),J.warning);else if(!tests.length)empty($('test-results'),'No recorded tests match this filter.');}
function sources(){const node=$('all-sources');node.append(el('h3','', 'Source records and integrity'));[E.source,J.source].filter(Boolean).forEach(s=>{node.append(link(s,s.name,true),el('p','source','SHA256 '+s.sha256));});if(!E.source&&!J.source)node.append(el('p','small','Source records were unavailable at build time.'));}
function init(){const s=E.summary,t=J.summary;$('hero-stats').append(stat(E.available?s.passed+' / '+s.total:'Unavailable','Recorded scenarios passed','Scenario runner · L1/L2 demonstrations'),stat(E.available?s.failed:'—','Recorded scenario failures','Failures are retained in the details'),stat(J.available?t.passed+' / '+t.total:'Unavailable','Whole-project tests passed','Full JUnit suite · all four levels'),stat(J.available?t.focused:'—','L1/L2 related test cases','Named module subset; not the whole suite'));const warnings=[...E.warnings,...(J.warning?[J.warning]:[])];if(s.failed||s.other)warnings.unshift('Attention: '+s.failed+' failed and '+s.other+' unclassified scenario results. This run does not establish a complete passing demonstration.');if(t.failed)warnings.unshift('Attention: the full-project JUnit record contains '+t.failed+' failed/error test cases.');warnings.forEach(message=>$('availability').append(el('div','callout warning',message)));$('evidence-date').textContent='Runner timestamp: '+(E.generated_at||'not recorded')+' · Source schema: '+(E.schema_version||'unavailable')+' · Display counts recomputed from recorded entries.';const scopes=[...new Set(E.scenarios.map(c=>c.scope))];scopes.forEach(scope=>$('scope-summary').append(badge(scope)));[...new Set(E.scenarios.map(c=>c.stage).filter(Boolean))].sort().forEach(stage=>{const o=el('option','',stage);o.value=stage;$('case-stage').append(o);});['case-search','case-stage','case-status'].forEach(id=>$(id).addEventListener(id==='case-search'?'input':'change',renderCases));renderCases();fillFeatureMatrix();fillCases('source-cases',/preserv|provenance|original|attachment|checksum|csv|pdf|log/i,3);fillCases('repair-cases',/repair|duplicate|malformed|missing.token|invalid.numeric/i,4);fillCases('units-cases',/unit|temperature|conversion|canonical|scale/i,3);fillCases('mixed-cases',/categor|state|narrative|mixed|text|log/i,3);fillCases('quality-cases',/expect|bound|stabil|flatline|required|quality/i,3);fillCases('timing-cases',/gap|timing|cadence|ordinal|sample.rate/i,3);fillCases('processing-cases',/process|align|fft|spectrum|analysis|rf|mechanical|plc/i,3);setupPlot('event-plot-select','event-plots','event');setupPlot('gap-plot-select','gap-plots','event',true);setupPlot('analysis-plot-select','analysis-plots','analysis');narrative();setupReports();$('test-stats').append(stat(J.available?t.total:'Unavailable','Whole-project test cases','Includes L1, L2, L3, L4 and project checks'),stat(J.available?t.focused:'—','L1/L2 related subset','Classified by test module names'),stat(J.available?t.failed:'—','Failures / errors','Testcase failure and error nodes'),stat(J.available?t.skipped:'—','Skipped','Explicit JUnit skip nodes'));['test-search','test-filter'].forEach(id=>$(id).addEventListener(id==='test-search'?'input':'change',renderTests));renderTests();if(J.source){$('junit-source').append(link(J.source,'Download full-suite JUnit XML',true),el('p','source','SHA256 '+J.source.sha256));}sources();}
const sections=[...document.querySelectorAll('.section')];let current=0,present=false;sections.forEach((section,i)=>{const a=el('a');a.href='#'+section.id;a.append(el('span','',String(i+1).padStart(2,'0')),document.createTextNode(section.dataset.title));a.addEventListener('click',event=>{if(present){event.preventDefault();show(i);}});$('nav').append(a);});function show(index){current=Math.max(0,Math.min(index,sections.length-1));sections.forEach((s,i)=>s.classList.toggle('selected',i===current));[...$('nav').children].forEach((a,i)=>a.classList.toggle('active',i===current));$('position').textContent=(current+1)+' / '+sections.length+' · '+sections[current].dataset.title;$('previous').disabled=current===0;sections[current].scrollIntoView({behavior:'instant',block:'start'});}function next(){if(present){const hidden=sections[current].querySelector('.reveal:not(.revealed)');if(hidden){hidden.classList.add('revealed');return;}}show(current+1);}function toggle(value){present=value;document.body.classList.toggle('presentation',present);$('present').textContent=present?'Exit presentation':'Start presentation';show(current);} $('present').addEventListener('click',()=>toggle(!present));$('exit').addEventListener('click',()=>toggle(false));$('next').addEventListener('click',next);$('previous').addEventListener('click',()=>show(current-1));document.addEventListener('keydown',event=>{if(/INPUT|SELECT|TEXTAREA|BUTTON/.test(document.activeElement.tagName)||event.ctrlKey||event.metaKey||event.altKey)return;if(['ArrowRight','PageDown'].includes(event.key)||(present&&event.key===' ')){event.preventDefault();next();}else if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();show(current-1);}else if(event.key==='Escape'&&present)toggle(false);else if(event.key==='Home'&&present)show(0);else if(event.key==='End'&&present)show(sections.length-1);});$('download-data').addEventListener('click',()=>{const blob=new Blob([json(DATA)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='showcase-display-data.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{const text=$(button.dataset.copy).textContent;try{await navigator.clipboard.writeText(text);$('copy-status').textContent='Command copied.';}catch(error){const area=el('textarea');area.value=text;document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();$('copy-status').textContent=copied?'Command copied.':'Clipboard unavailable. Select and copy the command text above.';}}));init();show(0);
</script></body></html>'''


def build_showcase(evidence, junit, output):
    output = Path(output).resolve()
    evidence_data = load_evidence(evidence, output)
    junit_data = load_junit(junit, output)
    payload = {"display_schema": "1.0", "evidence": evidence_data, "junit": junit_data,
               "scope_note": "Demonstrations and test results are separate. Full-suite tests cover all four levels; focused counts identify named L1/L2-related modules."}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    # JSON lives in a script data block. Escape HTML-significant characters so no
    # evidence string can terminate the block or inject executable markup.
    for original, replacement in [("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")]:
        encoded = encoded.replace(original, replacement)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__DATA__", encoded), encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("deliverables/L1_L2_Presentation/evidence"), help="Evidence directory or scenario_results.json")
    parser.add_argument("--junit", type=Path, help="Full-project pytest JUnit XML (default: evidence/pytest-results.xml)")
    parser.add_argument("--output", type=Path, default=Path("deliverables/L1_L2_Presentation/Feature_Showcase.html"))
    args = parser.parse_args(argv)
    directory = args.evidence if args.evidence.is_dir() or args.evidence.suffix.lower() != ".json" else args.evidence.parent
    junit = args.junit or next((directory / name for name in ["pytest-results.xml", "pytest.xml", "junit.xml"] if (directory / name).is_file()), directory / "pytest-results.xml")
    payload = build_showcase(args.evidence, junit, args.output)
    print(f"Created {args.output.resolve()}")
    print(f"Scenarios: {payload['evidence']['summary']} | Full-project tests: {payload['junit']['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
