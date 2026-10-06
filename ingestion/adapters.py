"""Adapters: turn an outside file format into canonical records.

Each adapter yields plain dicts that validate against schemas/. This is the
only place that knows anything about a particular dataset. Everything
downstream (Level 2 to 4) sees canonical records only.

Standard library only.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "0.1.0"


def _iso(text):
    """Parse 'YYYY-MM-DD hh:mm:ss[.ffffff]' and return ISO 8601 with Z.

    Neither dataset states a time zone. The timestamps are treated as UTC,
    which keeps intervals correct but not the absolute clock time.
    """
    text = text.strip()
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in text else "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _provenance(source, path, asset, acquired_at, mode=None, configuration=None):
    prov = {
        "source": {
            "system": source["title"],
            "uri": source["base_url"] + source["_rel"] if "_rel" in source else str(path),
            "license": source["license"],
        },
        "asset": asset,
        "acquired_at": acquired_at,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "synthetic": False,
        "checksum": _sha(path),
    }
    if mode:
        prov["operating_mode"] = mode
    if configuration:
        prov["configuration"] = configuration
    return prov


# --------------------------------------------------------------------------
# SKAB: pump testbed, semicolon-separated, about 1 Hz, labeled
# --------------------------------------------------------------------------

SKAB_CHANNELS = {
    "Accelerometer1RMS": ("g", "vibration acceleration"),
    "Accelerometer2RMS": ("g", "vibration acceleration"),
    "Current": ("A", "motor current"),
    "Pressure": ("bar", "loop pressure"),
    "Temperature": ("degC", "motor body temperature"),
    "Thermocouple": ("degC", "fluid temperature"),
    "Voltage": ("V", "motor voltage"),
    "Volume Flow RateRMS": ("L/min", "flow rate"),
}

SKAB_SCENARIOS = {
    "anomaly-free": "normal operation, no fault introduced",
    "valve1": "valve closed at the flow inlet to the pump",
    "valve2": "valve closed at the flow outlet of the pump",
    "other/1": "fluid leak and fluid addition", "other/2": "fluid leak and fluid addition",
    "other/3": "fluid leak and fluid addition", "other/4": "fluid leak and fluid addition",
    "other/5": "rotor imbalance, sharp", "other/6": "rotor imbalance, linear",
    "other/7": "rotor imbalance, step", "other/8": "rotor imbalance, impulse",
    "other/9": "rotor imbalance, exponential",
    "other/10": "slow increase of water in the circuit",
    "other/11": "sudden increase of water in the circuit",
    "other/12": "tank drained until cavitation",
    "other/13": "two-phase flow at pump inlet (cavitation)",
    "other/14": "water supplied at increased temperature",
}


def skab(path, source, rel):
    """One SKAB csv -> one timeseries record, plus one event_log if labeled."""
    path = Path(path)
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    if not rows:
        return
    stamps = [_iso(r["datetime"]) for r in rows]
    group = rel.split("/")[0]
    key = rel[:-4] if group == "other" else group
    slug = rel[:-4].replace("/", "-")
    event_id = f"skab-{slug}"
    source = dict(source, _rel=rel)
    asset = {"id": "SKAB-PUMP-01", "subsystem": "water circulation loop", "domain": "mechanical"}
    config = {"experiment": rel[:-4], "scenario": SKAB_SCENARIOS.get(key, "unknown")}
    prov = _provenance(source, path, asset, stamps[0],
                       mode="normal" if group == "anomaly-free" else "fault-injection test",
                       configuration=config)

    channels = []
    for col, (unit, quantity) in SKAB_CHANNELS.items():
        if col not in rows[0]:
            continue
        values = [_num(r[col]) for r in rows]
        ch = {"name": col, "unit": unit, "quantity": quantity, "t0": stamps[0],
              "timestamps": stamps, "values": values}
        if any(v is None for v in values):
            ch["quality"] = ["missing" if v is None else "good" for v in values]
        channels.append(ch)
    yield {"schema_version": SCHEMA_VERSION, "record_type": "timeseries",
           "record_id": f"ts-{event_id}", "event_id": event_id,
           "provenance": prov, "channels": channels}

    events, prev = [], 0
    for r, ts in zip(rows, stamps):
        if "anomaly" not in r:
            break
        cur = int(float(r["anomaly"] or 0))
        if cur != prev:
            events.append({"timestamp": ts, "name": "anomaly_label", "state_from": bool(prev),
                           "state_to": bool(cur), "severity": "alarm" if cur else "info",
                           "message": "Ground-truth anomaly window " + ("starts" if cur else "ends"),
                           "attributes": {"label_source": "dataset ground truth"}})
            prev = cur
        if int(float(r.get("changepoint") or 0)):
            events.append({"timestamp": ts, "name": "changepoint_label", "state_to": True,
                           "severity": "info", "message": "Ground-truth changepoint",
                           "attributes": {"label_source": "dataset ground truth"}})
    if events:
        yield {"schema_version": SCHEMA_VERSION, "record_type": "event_log",
               "record_id": f"log-{event_id}", "event_id": event_id,
               "provenance": prov, "events": events}


# --------------------------------------------------------------------------
# NAB: single-value csv files plus a json file of labeled anomaly windows
# --------------------------------------------------------------------------

NAB_META = {
    "machine_temperature_system_failure": ("NAB-MACHINE-01", "industrial machine internal component", "mechanical", "degF"),
    "ambient_temperature_system_failure": ("NAB-OFFICE-01", "office ambient temperature", "facilities", "degF"),
}


def nab(path, source, rel, windows=None):
    """One NAB csv -> one timeseries record, plus one event_log from its windows."""
    path = Path(path)
    stem = path.stem
    asset_id, subsystem, domain, unit = NAB_META.get(stem, (f"NAB-{stem}", stem, "unspecified", "1"))
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    stamps = [_iso(r["timestamp"]) for r in rows]
    values = [_num(r["value"]) for r in rows]
    event_id = f"nab-{stem.replace('_', '-')}"
    source = dict(source, _rel=rel)
    prov = _provenance(source, path, {"id": asset_id, "subsystem": subsystem, "domain": domain},
                       stamps[0],
                       configuration={"unit_note": "Unit is not stated by the dataset; degF is assumed from the value range."})
    yield {"schema_version": SCHEMA_VERSION, "record_type": "timeseries",
           "record_id": f"ts-{event_id}", "event_id": event_id, "provenance": prov,
           "channels": [{"name": "value", "unit": unit, "quantity": "temperature", "t0": stamps[0],
                         "timestamps": stamps, "values": values}]}
    events = []
    for start, end in (windows or {}).get(rel.replace("data/", "", 1), []):
        events.append({"timestamp": _iso(start), "name": "anomaly_window", "state_from": False,
                       "state_to": True, "severity": "alarm", "message": "Labeled anomaly window starts",
                       "attributes": {"label_source": "dataset ground truth"}})
        events.append({"timestamp": _iso(end), "name": "anomaly_window", "state_from": True,
                       "state_to": False, "severity": "info", "message": "Labeled anomaly window ends",
                       "attributes": {"label_source": "dataset ground truth"}})
    if events:
        yield {"schema_version": SCHEMA_VERSION, "record_type": "event_log",
               "record_id": f"log-{event_id}", "event_id": event_id, "provenance": prov, "events": events}


def convert_source(source, external_dir):
    """Yield every canonical record for one entry of data/sources.json."""
    folder = Path(external_dir) / source["id"]
    kind = source["adapter"]
    windows = None
    if kind == "nab":
        wpath = folder / "labels" / "combined_windows.json"
        windows = json.loads(wpath.read_text()) if wpath.exists() else {}
    for rel in source["files"]:
        path = folder / rel
        if not path.exists() or path.suffix != ".csv":
            continue
        if kind == "skab":
            yield from skab(path, source, rel)
        elif kind == "nab":
            yield from nab(path, source, rel, windows)
        else:
            raise ValueError(f"No adapter named {kind!r}")
