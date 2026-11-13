from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import uuid

from frib_ds.models import EngineeringEvent, Provenance

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 250_000
MAX_COLUMNS = 64
MAX_CELLS = 1_000_000
MAX_SAMPLES = 250_000
TABULAR_SUFFIXES = {".csv", ".tsv"}
SUPPORTED = TABULAR_SUFFIXES | {".txt", ".md", ".log", ".pdf"}
BOOLEAN = {"true", "false", "yes", "no", "on", "off", "enabled", "disabled", "open", "closed"}


def validate_upload(filename, contents):
    if not isinstance(filename, str) or not filename or len(filename) > 240 or any(char in filename for char in ("/", "\\", ":", "\x00", "\r", "\n")):
        raise ValueError("Choose a filename without a filesystem path.")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("Mixed imports support CSV, TSV, TXT, MD, LOG and text-based PDF files.")
    if not isinstance(contents, bytes) or not contents:
        raise ValueError("The uploaded file is empty.")
    if len(contents) > MAX_BYTES:
        raise ValueError("The uploaded file exceeds the 20 MB limit.")
    return suffix


def decode_text(contents):
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Save text, CSV and TSV files with UTF-8 encoding before importing.") from exc
    if "\x00" in text:
        raise ValueError("The file contains binary data; upload a UTF-8 text file.")
    return text


def severity(message):
    # Only explicit severity labels are classified; engineering wording is not diagnosis.
    match = re.search(r"(?:^\s*\[?|\[)(CRITICAL|FATAL|ERROR|ERR|WARNING|WARN|DEBUG|TRACE|INFO)(?:\]|\s|:|$)", message, re.IGNORECASE)
    if not match:
        return "INFO"
    value = match.group(1).upper()
    return {"FATAL": "CRITICAL", "ERR": "ERROR", "WARN": "WARNING"}.get(value, value)


def parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Use ISO date/time such as 2026-10-10T12:30:00Z.") from exc
    if "T" not in value and not re.search(r"\d{2}:\d{2}", value):
        raise ValueError("Date/time values must include a clock time.")
    naive = parsed.tzinfo is None
    if naive:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc), naive
    except (ValueError, OverflowError) as exc:
        # A syntactically valid boundary year can fall outside datetime's range
        # after applying its UTC offset. Treat it like other invalid source data.
        raise ValueError("Date/time is outside the supported UTC date range.") from exc


def make_event(filename, contents, options, signals, states, logs, summary, timestamp=None):
    if not isinstance(options.get("metadata", {}), dict):
        raise ValueError("'metadata' must be a JSON object.")
    metadata = dict(options.get("metadata") or {})
    summary["warnings"] = list(summary.get("notes", []))
    metadata.update(dataset_name=options.get("dataset_name") or Path(filename).stem,
                    source_filename=filename, imported=True, import_summary=summary)
    fields = dict(
        event_id=options.get("event_id") or f"IMPORT-{uuid.uuid4().hex[:12].upper()}",
        domain=options.get("domain") or "other", event_type="evidence_record",
        metadata=metadata, signals=signals, states=states, logs=logs,
        provenance=Provenance(source="uploaded_file", imported_by=options.get("imported_by"),
            checksum=hashlib.sha256(contents).hexdigest(),
            notes="Checksum identifies the original upload; categorical and narrative content is preserved as evidence without physical diagnosis."),
    )
    if timestamp is not None:
        fields["timestamp"] = timestamp
    return EngineeringEvent(**fields)


def severity_counts(logs):
    return dict(Counter(log.level for log in logs))
