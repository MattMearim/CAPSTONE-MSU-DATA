"""Config-driven synthetic event generator.

The engine knows nothing about any engineering field. Everything specific
(channels, faults, interlock sequences, procedures) lives in the JSON files
under generator/scenarios/ and generator/documents/. Adding a field means
adding a config file, not changing this code.

Standard library only. Output is fully determined by the seed.
"""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME = "synthgen"
VERSION = "0.1.0"
SCHEMA_VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def sig(v, digits=6):
    """Round to significant digits so small values (e.g. pressures) survive."""
    return float(f"{v:.{digits}g}")


def pick(spec, rng, cfg):
    """Resolve one parameter.

    number                    -> itself
    {"min": a, "max": b}      -> uniform random in [a, b]
    {"choice": [...]}         -> one of the list
    {"ref": "name", "scale"}  -> value from the event's sampled configuration
    """
    if isinstance(spec, dict):
        if "ref" in spec:
            return cfg[spec["ref"]] * spec.get("scale", 1.0) + spec.get("offset", 0.0)
        if "min" in spec and "max" in spec:
            return rng.uniform(spec["min"], spec["max"])
        if "choice" in spec:
            return rng.choice(spec["choice"])
    return spec


def resolve(item, rng, cfg):
    return {k: pick(v, rng, cfg) for k, v in item.items()}


# ---------------------------------------------------------------- signals

def add_baseline(y, t, comp, rng):
    kind = comp["type"]
    if kind == "constant":
        for i in range(len(y)):
            y[i] += comp["value"]
    elif kind == "sine":
        phase = comp.get("phase", rng.uniform(0, 2 * math.pi))
        w = 2 * math.pi * comp["freq_hz"]
        for i, ti in enumerate(t):
            y[i] += comp["amp"] * math.sin(w * ti + phase)
    elif kind == "noise":
        for i in range(len(y)):
            y[i] += rng.gauss(0, comp["sigma"])
    elif kind == "drift":
        for i, ti in enumerate(t):
            y[i] += comp["slope_per_s"] * ti
    elif kind == "random_walk":
        step = comp["sigma_per_sqrt_s"] * math.sqrt(t[1] - t[0]) if len(t) > 1 else 0
        acc = 0.0
        for i in range(len(y)):
            acc += rng.gauss(0, step)
            y[i] += acc
    else:
        raise ValueError(f"Unknown baseline component {kind!r}")


def apply_effect(y, missing, t, eff, t_fault, rng):
    """Apply one fault effect in place. Times are relative to the fault."""
    kind = eff["type"]
    t0 = t_fault + eff.get("delay_s", 0.0)
    t1 = t0 + eff["duration_s"] if "duration_s" in eff else float("inf")
    hold = None
    for i, ti in enumerate(t):
        if ti < t0:
            continue
        dt = ti - t0
        active = ti < t1
        if kind == "step":
            y[i] += eff["delta"]
        elif kind == "ramp":
            y[i] += eff["slope_per_s"] * min(dt, t1 - t0)
        elif kind == "exp_decay":
            target = eff.get("target_fraction", 0.0)
            y[i] *= target + (1 - target) * math.exp(-dt / eff["tau_s"])
        elif kind == "spike":
            y[i] += eff["amp"] * math.exp(-dt / eff["width_s"])
        elif kind == "oscillation" and active:
            y[i] += (eff["amp"] * math.exp(eff.get("growth_per_s", 0.0) * dt)
                     * math.sin(2 * math.pi * eff["freq_hz"] * dt))
        elif kind == "noise_burst" and active:
            y[i] += rng.gauss(0, eff["sigma"])
        elif kind == "dropout" and active:
            missing[i] = True
        elif kind == "freeze" and active:
            if hold is None:
                hold = y[i]
            y[i] = hold
        elif kind not in ("oscillation", "noise_burst", "dropout", "freeze"):
            raise ValueError(f"Unknown effect {kind!r}")


def build_channel(ch, effects, window, t_start, cfg, rng, imperfections):
    frozen = [e for e in effects if e.get("type") == "freeze"]
    effects = [e for e in effects if e.get("type") != "freeze"]
    fs = ch["sample_rate_hz"]
    n = int(round(window["duration_s"] * fs))
    t = [i / fs for i in range(n)]
    y = [0.0] * n
    missing = [False] * n
    # Process signal first, then fault effects, then measurement noise, so a
    # signal that decays to zero still shows the sensor's noise floor.
    process = [c for c in ch["baseline"] if c["type"] != "noise"]
    sensor_noise = [c for c in ch["baseline"] if c["type"] == "noise"]
    for comp in process:
        add_baseline(y, t, resolve(comp, rng, cfg), rng)
    for eff in effects:
        apply_effect(y, missing, t, resolve(eff, rng, cfg), window["pre_fault_s"], rng)
    for comp in sensor_noise:
        add_baseline(y, t, resolve(comp, rng, cfg), rng)
    for eff in frozen:                       # a stuck reading repeats exactly
        apply_effect(y, missing, t, resolve(eff, rng, cfg), window["pre_fault_s"], rng)
    lo, hi = ch.get("min"), ch.get("max")
    if lo is not None or hi is not None:
        y = [min(hi, v) if hi is not None else v for v in y]
        y = [max(lo, v) if lo is not None else v for v in y]
    # Realism: an occasional short gap unrelated to any fault.
    if rng.random() < imperfections.get("gap_probability", 0.0):
        length = max(1, int(n * rng.uniform(0.002, imperfections.get("gap_max_fraction", 0.01))))
        start = rng.randrange(0, max(1, n - length))
        for i in range(start, start + length):
            missing[i] = True
    out = {"name": ch["name"], "unit": ch["unit"]}
    if "quantity" in ch:
        out["quantity"] = ch["quantity"]
    out.update({"t0": iso(t_start), "sample_rate_hz": fs,
                "values": [None if m else sig(v) for v, m in zip(y, missing)]})
    if any(missing):
        out["quality"] = ["missing" if m else "good" for m in missing]
    return out


# ----------------------------------------------------------------- events

def build_event(domain, scenario, index, t_start, seed, run_id):
    """Return (records, truth) for one operational event."""
    rng = random.Random(f"{seed}:{index}")
    cfg = {}
    for key, spec in domain.get("configuration", {}).items():
        value = pick(spec, rng, cfg)
        cfg[key] = sig(value) if isinstance(value, float) else value
    asset = dict(rng.choice(domain["assets"]), domain=domain["domain"])
    window = domain["window"]
    t_fault = t_start + timedelta(seconds=window["pre_fault_s"])
    event_id = f"evt-{run_id}-{index:04d}"
    prov = {
        "source": {"system": "synthetic-generator", "instrument": domain.get("instrument", "simulated")},
        "asset": asset,
        "operating_mode": rng.choice(domain.get("operating_modes", ["operating"])),
        "configuration": cfg,
        "acquired_at": iso(t_start),
        "synthetic": True,
        "generator": {"name": NAME, "version": VERSION, "seed": seed, "scenario": scenario["id"]},
    }
    by_channel = {}
    for eff in scenario.get("effects", []):
        targets = eff["channel"] if isinstance(eff["channel"], list) else [eff["channel"]]
        for name in targets:
            by_channel.setdefault(name, []).append({k: v for k, v in eff.items() if k != "channel"})
    known = {c["name"] for c in domain["channels"]}
    unknown = set(by_channel) - known
    if unknown:
        raise ValueError(f"Scenario {scenario['id']!r} references unknown channels {sorted(unknown)}")
    channels = [build_channel(c, by_channel.get(c["name"], []), window, t_start, cfg, rng,
                              domain.get("imperfections", {})) for c in domain["channels"]]
    ts = {"schema_version": SCHEMA_VERSION, "record_type": "timeseries",
          "record_id": f"ts-{event_id}", "event_id": event_id, "provenance": prov, "channels": channels}

    events = [{"timestamp": iso(t_start), "name": "CAPTURE_START", "state_to": True,
               "severity": "info", "message": "Data capture window opened"}]
    for ev in scenario.get("events", []):
        jitter = rng.uniform(-1, 1) * ev.get("jitter_s", 0.0)
        e = {"timestamp": iso(t_fault + timedelta(seconds=ev["offset_s"] + jitter)),
             "name": ev["name"], "state_to": ev["state_to"]}
        for key in ("state_from", "severity", "message", "attributes"):
            if key in ev:
                e[key] = ev[key]
        events.append(e)
    events.sort(key=lambda e: e["timestamp"])
    log = {"schema_version": SCHEMA_VERSION, "record_type": "event_log",
           "record_id": f"log-{event_id}", "event_id": event_id, "provenance": prov, "events": events}

    truth = {"event_id": event_id, "domain": domain["domain"], "asset_id": asset["id"],
             "scenario": scenario["id"], "label": scenario.get("label", scenario["id"]),
             "is_fault": bool(scenario.get("effects") or scenario.get("events")),
             "description": scenario.get("description", ""),
             "window_start": iso(t_start), "fault_time": iso(t_fault),
             "record_ids": [ts["record_id"], log["record_id"]],
             "relevant_documents": scenario.get("documents", [])}
    return [ts, log], truth


def build_documents(domain, docs, seed, start):
    out = []
    for d in docs:
        rec = {"schema_version": SCHEMA_VERSION, "record_type": "document",
               "record_id": d["record_id"],
               "provenance": {
                   "source": {"system": "synthetic-generator", "instrument": "authored fictional procedure"},
                   "asset": {"id": d.get("asset_id", f"{domain.upper()}-ALL"), "domain": domain},
                   "acquired_at": iso(start), "synthetic": True,
                   "generator": {"name": NAME, "version": VERSION, "seed": seed, "scenario": "documents"}}}
        for key in ("title", "doc_type", "revision", "status", "effective_date",
                    "superseded_by", "applies_to", "sections"):
            if key in d:
                rec[key] = d[key]
        out.append(rec)
    return out


# -------------------------------------------------------------------- run

def load_domains(scenario_dir=None):
    scenario_dir = Path(scenario_dir or HERE / "scenarios")
    domains = {}
    for path in sorted(scenario_dir.glob("*.json")):
        cfg = json.loads(path.read_text())
        domains[cfg["domain"]] = cfg
    return domains


def load_documents(document_dir=None):
    document_dir = Path(document_dir or HERE / "documents")
    return {p.stem: json.loads(p.read_text())["documents"] for p in sorted(document_dir.glob("*.json"))}


def generate(seed=42, events=30, domains=None, scenario=None, start="2026-01-05T08:00:00",
             scenario_dir=None, document_dir=None):
    """Return (records, manifest). Same arguments always give the same output."""
    all_domains = load_domains(scenario_dir)
    names = domains or sorted(all_domains)
    missing = [n for n in names if n not in all_domains]
    if missing:
        raise ValueError(f"Unknown domain(s) {missing}; available: {sorted(all_domains)}")
    rng = random.Random(f"{seed}:plan")
    clock = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    run_id = f"s{seed}"
    records, truths = [], []
    for i in range(events):
        dom = all_domains[names[i % len(names)]]            # even spread across domains
        pool = [s for s in dom["scenarios"] if scenario in (None, s["id"])]
        if not pool:
            continue
        scen = rng.choices(pool, weights=[s.get("weight", 1) for s in pool])[0]
        clock += timedelta(minutes=rng.uniform(20, 600))
        recs, truth = build_event(dom, scen, i, clock, seed, run_id)
        records += recs
        truths.append(truth)
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    docs = load_documents(document_dir)
    n_docs = 0
    for name in names:
        d = build_documents(name, docs.get(name, []), seed, start_dt)
        records += d
        n_docs += len(d)
    manifest = {"generator": {"name": NAME, "version": VERSION}, "seed": seed,
                "arguments": {"events": events, "domains": names, "scenario": scenario, "start": start},
                "counts": {"events": len(truths), "documents": n_docs, "records": len(records)},
                "note": "Ground truth for validation. The decision-support system must never read this file.",
                "events": truths}
    return records, manifest


def write(records, manifest, out_dir):
    out_dir = Path(out_dir)
    (out_dir / "records").mkdir(parents=True, exist_ok=True)
    for rec in records:
        (out_dir / "records" / f"{rec['record_id']}.json").write_text(json.dumps(rec) + "\n")
    (out_dir / "ground_truth.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out_dir
