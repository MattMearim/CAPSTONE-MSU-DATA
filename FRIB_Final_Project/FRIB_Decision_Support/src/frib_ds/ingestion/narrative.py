from __future__ import annotations

from collections import Counter
import io
from pathlib import Path
import re

from frib_ds.models import LogEntry, StateEvent
from frib_ds.units import convert_value, parse_quantity
from .common import BOOLEAN, MAX_BYTES, MAX_ROWS, make_event, decode_text, parse_datetime, severity, severity_counts


_DATE = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?\s*(?:[-|:]\s*)?(.*)$")
_RELATIVE = re.compile(r"^\s*\[?([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*(?:ns|us|µs|μs|ms|s|min|h))(?=\s|\]|[-|:]|$)\]?\s*(?:[-|:]\s*)?(.*)$")
_ASSIGNMENT = re.compile(r'''\b([A-Za-z_][A-Za-z0-9_.:-]{0,63})\s*=\s*(?:"([^"\r\n]{1,200})"|'([^'\r\n]{1,200})'|([A-Za-z_][A-Za-z0-9_.:/-]{0,79}))(?=\s|[,;]|$)''')


def read_document(filename, contents):
    notes, records = [], []
    if Path(filename).suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(contents))
        except ImportError as exc:
            raise ValueError("PDF text extraction needs pypdf; run the project setup to install dependencies.") from exc
        except Exception as exc:
            raise ValueError("PDF text could not be extracted. Upload a readable, unencrypted text-based PDF or export it as UTF-8 text.") from exc
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported; export an unencrypted text-based PDF.")
        if len(reader.pages) > 500:
            raise ValueError("PDF exceeds the limit of 500 pages; import a smaller document.")
        pages = extract_pages(reader)
        notes.append("PDF import extracts text only; images, scanned pages, layout and tables are not interpreted. OCR is not available.")
    else:
        pages = [(None, decode_text(contents))]
    line_number = 0
    for page, text in pages:
        for page_line, message in enumerate(text.splitlines(), 1):
            line_number += 1
            if not message.strip():
                continue
            records.append({"line": line_number, "page": page, "page_line": page_line, "message": message})
            if len(records) > MAX_ROWS:
                raise ValueError("Document exceeds 250,000 nonempty lines; import a smaller document.")
    if not records:
        if Path(filename).suffix.lower() == ".pdf":
            raise ValueError("PDF contains no extractable text. Scanned PDFs need OCR outside this application; upload TXT/MD/LOG or a text-based PDF.")
        raise ValueError("The document contains no nonempty text lines.")
    return records, notes


def extract_pages(reader):
    total = 0
    for number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ValueError(f"PDF text extraction failed on page {number}; export a readable text-based PDF or UTF-8 text file.") from exc
        total += len(text)
        if total > MAX_BYTES:
            raise ValueError("PDF extracted text exceeds 20 million characters; import a smaller document.")
        yield number, text


def timestamp_prefix(message):
    match = _DATE.match(message)
    if match:
        parsed, naive = parse_datetime(match.group(1))
        return "datetime", parsed, match.group(2), match.group(1), naive
    match = _RELATIVE.match(message)
    if match:
        number, unit = parse_quantity(match.group(1))
        return "s", convert_value(number, unit, "s"), match.group(2), match.group(1), False
    return None, None, message, None, False


def inspect_document(filename, contents):
    records, notes = read_document(filename, contents)
    prefixes = [timestamp_prefix(record["message"]) for record in records]
    kinds = {prefix[0] for prefix in prefixes}
    basis = next(iter(kinds)) if len(kinds) == 1 and None not in kinds else "row_index"
    if basis == "row_index":
        notes.append("Lines use unitless row-order coordinates because consistent timestamps were not found; these positions are not measured seconds.")
    return {"filename": filename, "format": "pdf" if Path(filename).suffix.lower() == ".pdf" else "text",
        "row_count": len(records), "columns": [],
        "sample_rows": [{"line": record["line"], "message": record["message"]} for record in records[:6]],
        "text_preview": "\n".join(record["message"] for record in records)[:4000],
        "suggested_time_column": None, "suggested_time_unit": basis, "warnings": notes}


def build_document(filename, contents, options):
    records, notes = read_document(filename, contents)
    prefixes = [timestamp_prefix(record["message"]) for record in records]
    kinds = {prefix[0] for prefix in prefixes}
    basis = next(iter(kinds)) if len(kinds) == 1 and None not in kinds else "row_index"
    if options.get("time_unit") == "row_index":
        basis = "row_index"
    anchor = min(prefix[1] for prefix in prefixes) if basis == "datetime" else None
    if basis == "row_index":
        notes.append("Time coordinates use unitless line order; seconds fields are storage placeholders, not measured timing. Original timestamp prefixes, when present, remain in each log entry.")
        if any(prefix[0] is not None for prefix in prefixes):
            notes.append("Missing or mixed timestamp formats prevent a shared measured timeline; all lines use row order consistently.")
    if any(prefix[4] for prefix in prefixes):
        notes.append("Date/time values without an offset were stored as UTC; verify the source timezone.")
    timed = []
    for ordinal, (record, prefix) in enumerate(zip(records, prefixes)):
        timestamp = float(ordinal) if basis == "row_index" else ((prefix[1] - anchor).total_seconds() if basis == "datetime" else prefix[1])
        timed.append((timestamp, ordinal, record, prefix))
    ordered = sorted(timed, key=lambda item: item[0])
    if [item[1] for item in ordered] != list(range(len(records))):
        notes.append("Derived logs and state changes were ordered by supplied timestamps; the preserved upload retains its original order.")
    logs, states, previous, frequencies = [], [], {}, {}
    for timestamp, _, record, prefix in ordered:
        metadata = {"source_line": record["line"], "inferred_time": basis == "row_index"}
        if record["page"] is not None:
            metadata.update(source_page=record["page"], source_page_line=record["page_line"])
        if prefix[3] is not None:
            metadata["original_timestamp"] = prefix[3]
        logs.append(LogEntry(timestamp_s=timestamp, level=severity(prefix[2]), message=record["message"],
            source=f"{filename}:line {record['line']}", metadata=metadata))
        for match in _ASSIGNMENT.finditer(prefix[2]):
            name, value = match.group(1), next(value for value in match.groups()[1:] if value is not None)
            # Only explicit categorical assignments are states. Prose and physical numbers remain logs.
            try:
                parse_quantity(value)
                continue
            except ValueError:
                pass
            frequencies.setdefault(name, Counter())[value] += 1
            comparable = value.lower() if value.lower() in BOOLEAN else value
            if previous.get(name, object()) != comparable:
                states.append(StateEvent(timestamp_s=timestamp, name=name, value=value, metadata=dict(metadata)))
                previous[name] = comparable
        if len(logs) + len(states) > MAX_ROWS:
            raise ValueError("Document exceeds 250,000 derived log/state records; import a smaller document.")
    notes.append("Every nonempty line is retained as a log. Only explicit name=value categorical assignments become state changes; narrative text is not converted into a physical diagnosis.")
    summary = {"format": "pdf" if Path(filename).suffix.lower() == ".pdf" else "text",
        "input_rows": len(records), "retained_rows": len(records), "numeric_signals": 0,
        "state_changes": len(states), "log_entries": len(logs), "column_roles": {}, "column_types": {},
        "category_frequencies": {name: dict(counts) for name, counts in frequencies.items()},
        "log_severity_distribution": severity_counts(logs), "unit_conversions": [],
        "time_basis": basis, "time_column": None, "notes": list(dict.fromkeys(notes))}
    return make_event(filename, contents, options, [], states, logs, summary, anchor)
