"""Inspect raw evidence and apply only explicitly requested, auditable CSV edits.

Assessment tolerates bad row shapes so several problems can be reviewed together.
It never changes bytes, assigns an inferred physical unit, or fills missing data.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import math
from pathlib import Path
import re

from frib_ds.units import convert_value, normalize_unit, parse_quantity, quantity_parts, unit_catalog
from .common import MAX_BYTES, MAX_CELLS, MAX_COLUMNS, MAX_ROWS, TABULAR_SUFFIXES, decode_text, parse_datetime, validate_upload
from .tabular import TIME_UNITS, header_details, mapping, profile_csv

_EXAMPLES = 25
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NONFINITE = re.compile(r"^[+-]?(?:nan|inf(?:inity)?)(?:\s+.*)?$", re.I)
_MISSING = {"NA", "N/A", "NULL", "NAN", "+NAN", "-NAN", "NONE", "MISSING", "#N/A"}
_SENTINELS = {-999.0, -9999.0, -99999.0, 9999.0, 99999.0}
_UNITS = {unit["symbol"]: unit for unit in unit_catalog()}
_REPAIRS = {"drop_exact_duplicate_rows", "sort_by_time", "mark_missing_tokens", "drop_malformed_rows", "drop_invalid_numeric_cells"}


class _Issues:
    def __init__(self):
        self.entries = {}

    def add(self, code, severity, title, message, *, column=None, row=None, timestamp=None, count=1, suggestion="", repair=None):
        key = code, column, severity
        issue = self.entries.setdefault(key, {"code": code, "severity": severity, "title": title, "message": message,
            "column": column, "rows": [], "timestamps_s": [], "count": 0, "suggestion": suggestion, "repair": repair})
        issue["count"] += count
        if row is not None and len(issue["rows"]) < _EXAMPLES and row not in issue["rows"]:
            issue["rows"].append(row)
        if timestamp is not None and math.isfinite(timestamp) and len(issue["timestamps_s"]) < _EXAMPLES:
            issue["timestamps_s"].append(timestamp)

    def report(self, suggestions=None):
        issues = list(self.entries.values())
        summary = {severity: sum(issue["severity"] == severity for issue in issues) for severity in ("error", "warning", "info")}
        return {"version": "1.0", "stage": "L1", "status": "blocked" if summary["error"] else ("review" if summary["warning"] else "ok"),
            "summary": summary, "issues": issues, "unit_suggestions": suggestions or []}


def _read(contents, issues):
    """Return intact records, including malformed shapes, without guessing quotes."""
    try:
        text = decode_text(contents)
    except ValueError as exc:
        issues.add("unreadable_text", "error", "Text cannot be decoded", str(exc), suggestion="Export the original as UTF-8 CSV. Encoding and binary data are not repaired automatically.")
        return None
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        try:
            dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t|")
        except (csv.Error, IndexError):
            dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
    records, layout, header, raw_header, cells, previous = [], [], None, None, 0, 0
    complete = True
    try:
        raw_header = next(reader)
        header = [cell.strip() for cell in raw_header]
        previous = reader.line_num
        if not header or not all(header):
            issues.add("empty_header", "error", "Missing column names", "Every CSV column requires a nonempty name.", row=previous, suggestion="Correct the header in a copy of the source file.")
        if len(header) > MAX_COLUMNS:
            issues.add("column_limit", "error", "Too many columns", f"CSV exceeds the limit of {MAX_COLUMNS} columns.", row=previous, suggestion="Split the file or remove unneeded columns in a source copy.")
            return None
        for name, count in Counter(header).items():
            if count > 1:
                issues.add("duplicate_headers", "error", "Duplicate column name", f"Header {name!r} occurs {count} times; column mappings would be ambiguous.", column=name, row=previous, count=count, suggestion="Assign a distinct header to each source column.")
        for row in reader:
            end, start = reader.line_num, previous + 1
            previous = end
            cells += len(row)
            if len(layout) >= MAX_ROWS or cells > MAX_CELLS:
                issues.add("inspection_limit", "error", "Inspection limit exceeded", "CSV exceeds 250,000 rows or 1,000,000 cells; remaining data was not inspected.", row=start, suggestion="Split the capture into smaller files and inspect each complete file.")
                complete = False
                break
            record = {"row": start, "end_row": end, "cells": row, "blank": not any(cell.strip() for cell in row)}
            layout.append(record)
            if record["blank"]:
                continue
            records.append(record)
            if len(row) != len(header):
                issues.add("row_shape", "error", "CSV row has the wrong field count", f"Rows must contain {len(header)} fields; listed source rows have fewer or additional fields.", row=start,
                    suggestion="Correct the source row, or explicitly select malformed rows to exclude while retaining the original.", repair={"operation": "drop_malformed_rows", "rows": []})
    except StopIteration:
        issues.add("empty_file", "error", "Empty CSV", "CSV has no header or data.", suggestion="Upload a CSV containing a header and evidence rows.")
        return None
    except csv.Error as exc:
        issues.add("csv_syntax", "error", "Unreadable CSV quoting or truncated record", f"CSV parsing stopped at physical row {reader.line_num}: {exc}.", row=reader.line_num,
            suggestion="Correct quotation marks or recover the complete source file. Malformed quoting is not repaired automatically.")
        complete = False
    if header is None:
        return None
    if not records:
        issues.add("no_data_rows", "error", "No evidence rows", "CSV contains no nonempty data rows.", suggestion="Upload the complete capture with data beneath the header.")
    if records and len(records[-1]["cells"]) < len(header) and not text.endswith(("\n", "\r")):
        issues.add("possible_truncation", "warning", "Last record may be truncated", "The final record has fewer fields and no ending newline. This is a structural clue, not proof of data loss.", row=records[-1]["row"], suggestion="Compare the upload with its source export before excluding the record.")
    return {"headers": header, "raw_header": raw_header, "records": records, "layout": layout, "delimiter": dialect.delimiter,
        "line_ending": "\r\n" if "\r\n" in text else "\n", "bom": contents.startswith(b"\xef\xbb\xbf"), "complete": complete}


def _settings(data, options):
    headers = data["headers"]
    if not isinstance(options, dict):
        raise ValueError("Import options must be a JSON object.")
    if not isinstance(options.get("metadata", {}), dict):
        raise ValueError("metadata must be a JSON object.")
    mappings = {key: mapping(options, key, headers) for key in ("column_roles", "signal_names", "source_units", "target_units", "unit_columns")}
    for key, values in mappings.items():
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError(f"{key} values must be strings.")
    if any(role not in {"numeric", "category", "log", "ignore"} for role in mappings["column_roles"].values()):
        raise ValueError("Column roles must be numeric, category, log or ignore.")
    valid = [(record["row"], record["cells"]) for record in data["records"] if len(record["cells"]) == len(headers)]
    profiles, suggested_time, suggested_unit, _ = profile_csv(headers, valid)
    roles = {profile["name"]: mappings["column_roles"].get(profile["name"], profile["suggested_role"]) for profile in profiles}
    unit_columns = dict(mappings["unit_columns"])
    for profile in profiles:
        if profile.get("suggested_unit_column"):
            unit_columns.setdefault(profile["name"], profile["suggested_unit_column"])
    for column in unit_columns.values():
        if column not in headers:
            raise ValueError(f"Unit column {column!r} does not exist.")
        if column not in mappings["column_roles"]:
            roles[column] = "ignore"
    time_column = options.get("time_column", suggested_time)
    if time_column is not None and not isinstance(time_column, str):
        raise ValueError("time_column must be a column name or null.")
    if time_column in {"", "none", "row_index"}:
        time_column = None
    if time_column is not None and time_column not in headers:
        raise ValueError(f"Time column {time_column!r} does not exist.")
    time_unit = options.get("time_unit", suggested_unit if time_column else "row_index")
    if not isinstance(time_unit, str) or time_unit not in TIME_UNITS | {"datetime", "row_index"}:
        raise ValueError("Select a supported time unit or datetime/row_index.")
    if time_unit == "row_index":
        time_column = None
    if time_column:
        roles[time_column] = "ignore"
    policy = options.get("invalid_rows", "reject")
    if not isinstance(policy, str) or policy not in {"reject", "skip"}:
        raise ValueError("invalid_rows must be reject or skip.")
    return {**mappings, "roles": roles, "unit_columns": unit_columns, "time_column": time_column,
        "time_unit": time_unit, "invalid_severity": "warning" if policy == "skip" else "error", "profiles": profiles}


def _time(cell, unit):
    if unit == "datetime":
        parsed, _ = parse_datetime(cell)
        return parsed.timestamp()
    value, source = parse_quantity(cell, unit)
    return convert_value(value, source, "s")


def _numeric(cell, default, row_unit=None, target=None):
    value, source = parse_quantity(cell, row_unit or default)
    if row_unit:
        convert_value(value, source, row_unit)
    if target:
        convert_value(value, source, target)
    return value, source


def _suggestions(column, header_unit, observations, has_bare, source_override=None):
    candidates = []
    def add(unit, confidence, evidence):
        try:
            unit = normalize_unit(unit)
        except ValueError:
            return
        existing = next((candidate for candidate in candidates if candidate["unit"] == unit), None)
        if existing:
            existing["evidence"].append(evidence)
        else:
            candidates.append({"unit": unit, "confidence": confidence, "evidence": [evidence]})
    if source_override:
        add(source_override, "high", "The source unit was explicitly selected in import options; this report does not assign it.")
    if header_unit:
        add(header_unit, "high", f"The source header explicitly declares {header_unit!r}; verify the export convention.")
    for unit, count in observations.items():
        add(unit, "high", f"{count} sample(s) use explicit cell, header or per-row unit declarations identifying {unit}.")
    if not candidates and has_bare:
        base = header_details(column)[0]
        suffix = re.search(r"(?:_|\s)([^_\s]+)$", base)
        if suffix:
            add(suffix.group(1), "medium", "The column-name suffix resembles a supported unit; confirm it before applying a source-unit mapping.")
        name = re.sub(r"[^a-z0-9]", " ", base.lower())
        families = [
            (r"pressure|vacuum", ["Pa", "kPa", "bar", "Torr"], "pressure"),
            (r"voltage|volt", ["V", "mV", "kV"], "voltage"),
            (r"temperature|temp", ["C", "K", "F"], "temperature; numbers alone cannot establish its offset scale"),
            (r"gradient", ["V/m", "kV/m", "MV/m"], "field gradient"),
            (r"power", ["W", "kW", "MW"], "power"),
            (r"frequency|freq", ["Hz", "kHz", "MHz"], "frequency"),
            (r"acceleration|accelerometer", ["m/s^2", "g"], "acceleration"),
            (r"displacement|position|length", ["m", "mm", "um"], "length"),
        ]
        for pattern, units, description in families:
            if re.search(pattern, name):
                if "temperature" in description and re.search(r"delta|difference", name):
                    units, description = ["delta_C", "delta_K", "delta_F"], "temperature difference; absolute and difference units are distinct"
                for unit in units:
                    add(unit, "low", f"Column name suggests {description}. This is a name-based candidate, not measured unit evidence.")
    if not candidates:
        return None
    return {"column": column, "candidates": candidates, "requires_confirmation": True, "assigned": False}


def _assess_csv(data, options, issues):
    try:
        settings = _settings(data, options)
    except ValueError as exc:
        issues.add("invalid_options", "error", "Invalid import mapping", str(exc), suggestion="Correct column mappings and option types before importing.")
        return []
    headers = data["headers"]
    valid = [record for record in data["records"] if len(record["cells"]) == len(headers)]
    seen = set()
    for record in valid:
        key = tuple(record["cells"])
        if key in seen:
            issues.add("duplicate_rows", "warning", "Exact duplicate evidence row", "These records repeat all parsed field values exactly; they may be repeated acquisition evidence or redundant export rows.", row=record["row"],
                suggestion="Verify the export convention before explicitly excluding redundant copies.", repair={"operation": "drop_exact_duplicate_rows"})
        else:
            seen.add(key)
    time_column, time_unit = settings["time_column"], settings["time_unit"]
    timestamps = {}
    if time_column:
        index, seen_times, previous, anchor = headers.index(time_column), {}, None, None
        declared = header_details(time_column)[1]
        if declared and declared not in TIME_UNITS and "time_unit" not in options:
            issues.add("unsupported_time_unit", "error", "Time unit is not compatible", f"Time header declares {declared!r}; the strict importer needs an explicitly corrected time_unit.", column=time_column, suggestion="Confirm and explicitly select the source time unit.")
        if not declared and "time_unit" not in options:
            first_cell = next((record["cells"][index].strip() for record in valid if record["cells"][index].strip()), "")
            name_has_unit = re.search(r"(?:ms|us|ns|s)$", re.sub(r"[^a-z0-9]", "", time_column.lower()))
            if re.fullmatch(_NUMBER, first_cell) and not name_has_unit:
                issues.add("time_unit_unconfirmed", "warning", "Timestamp unit is unconfirmed", "Bare timestamp numbers do not establish seconds; the importer currently suggests seconds until a source time unit is selected.", column=time_column, suggestion="Confirm the acquisition time unit and select it explicitly before interpreting durations or rates.")
        for record in valid:
            try:
                timestamp = _time(record["cells"][index], time_unit)
                anchor = timestamp if anchor is None else anchor
                relative = timestamp - anchor if time_unit == "datetime" else timestamp
                timestamps[record["row"]] = relative
                present_numeric = set()
                for name, role in settings["roles"].items():
                    if role != "numeric":
                        continue
                    cell = record["cells"][headers.index(name)]
                    unit_column = settings["unit_columns"].get(name)
                    row_unit = record["cells"][headers.index(unit_column)].strip() if unit_column else None
                    try:
                        _numeric(cell, settings["source_units"].get(name, header_details(name)[1] or ""), row_unit)
                        present_numeric.add(name)
                    except ValueError:
                        pass
                if timestamp in seen_times:
                    severity = settings["invalid_severity"] if present_numeric & seen_times[timestamp] else "warning"
                    issues.add("duplicate_timestamps", severity, "Repeated source timestamp", "Two or more source records share a timestamp. Numeric channels require distinct increasing sample times; categorical/log records can legitimately coincide.", column=time_column, row=record["row"], timestamp=relative,
                        suggestion="Resolve repeated numeric samples in the source; sorting cannot remove timestamp ambiguity.")
                if previous is not None and timestamp < previous:
                    issues.add("time_reversal", "warning", "Source timestamps move backward", "The listed records occur earlier than their preceding source record. Derived import sorts measured times; raw order remains provenance evidence.", column=time_column, row=record["row"], timestamp=relative,
                        suggestion="Review the clock/export ordering before an explicit stable sort.", repair={"operation": "sort_by_time"})
                seen_times.setdefault(timestamp, set()).update(present_numeric)
                previous = timestamp
            except ValueError:
                issues.add("invalid_timestamp", settings["invalid_severity"], "Timestamp is missing or unreadable", "Timestamp cells must be finite time quantities or the selected ISO datetime format.", column=time_column, row=record["row"], suggestion="Correct the timestamp, or explicitly select the existing skip-invalid policy. Timestamp values are never invented.")
    else:
        issues.add("inferred_time", "warning", "No measured time axis", "Rows will use unitless ordinal positions; stored seconds/sample-rate fields are placeholders.", suggestion="Select a measured timestamp column and its unit when available.")
    suggestions = []
    for index, column in enumerate(headers):
        if column == time_column or column in settings["unit_columns"].values():
            continue
        role = settings["roles"][column]
        explicit_role = settings["column_roles"].get(column)
        declared = settings["source_units"].get(column, header_details(column)[1] or "")
        header_unit = header_details(column)[1]
        rows_nonempty = [(record, record["cells"][index].strip()) for record in valid if record["cells"][index].strip()]
        possible_numeric = any(quantity_parts(cell) is not None for _, cell in rows_nonempty)
        measurement = role == "numeric"
        possible_placeholder = any(cell.upper() in _MISSING or _NONFINITE.fullmatch(cell) for _, cell in rows_nonempty)
        candidate = measurement or (explicit_role is None and (possible_numeric or possible_placeholder))
        missing = [record["row"] for record in valid if not record["cells"][index].strip()]
        for row in missing:
            issues.add("missing_cells", "warning", "Missing source cell", "Blank cells remain absent; no values will be filled or interpolated.", column=column, row=row, timestamp=timestamps.get(row), suggestion="Review missing coverage and retain gaps unless the source provides a measured value.")
        if not candidate or explicit_role in {"category", "log", "ignore"}:
            continue
        severity = settings["invalid_severity"] if measurement else "warning"
        try:
            default = normalize_unit(declared)
            target = normalize_unit(settings["target_units"][column]) if column in settings["target_units"] else (default if declared else None)
        except ValueError as exc:
            issues.add("unsupported_unit", "error" if measurement else "warning", "Unsupported declared unit", str(exc), column=column, suggestion="Select a supported source/target unit after confirming the source convention; unsupported units are not erased automatically.")
            continue
        if header_unit and not declared:
            try:
                normalize_unit(header_unit)
            except ValueError:
                issues.add("unsupported_unit", "error", "Unsupported source declaration remains unresolved", f"The header declares {header_unit!r}; an empty source-unit mapping does not confirm a replacement.", column=column, suggestion="Explicitly select a supported nonempty replacement or correct the source header.")
        unit_index = headers.index(settings["unit_columns"][column]) if column in settings["unit_columns"] else None
        observed, numeric_count, sample_times, has_bare = Counter(), 0, set(), False
        for record, cell in rows_nonempty:
            row, row_unit = record["row"], (record["cells"][unit_index].strip() if unit_index is not None else "")
            match = quantity_parts(cell)
            if cell.upper() in _MISSING:
                message = "Recognized NA/N/A/NULL/NaN-style markers are not numeric measurements." if measurement else "NA/N/A/NULL/NaN-style strings may be missing measurements or literal categorical values; confirm the column role."
                issues.add("missing_tokens", severity, "Possible missing-value placeholder", message, column=column, row=row, timestamp=timestamps.get(row),
                    suggestion="Explicitly mark recognized tokens as missing only in a confirmed numeric field; no replacement measurement is created.", repair={"operation": "mark_missing_tokens", "columns": [column]} if measurement else None)
                continue
            if _NONFINITE.fullmatch(cell):
                issues.add("nonfinite_values", severity, "Nonfinite numeric value", "Infinity and NaN cannot be stored as measured numeric samples.", column=column, row=row, timestamp=timestamps.get(row),
                    suggestion="Correct the source or explicitly exclude selected invalid cells in a confirmed numeric field.", repair={"operation": "drop_invalid_numeric_cells", "columns": [column], "rows": []} if measurement else None)
                continue
            if not match:
                issues.add("mixed_numeric_text", severity, "Text occurs among possible measurements", "This field contains nonnumeric text. It must remain text or be explicitly excluded from a confirmed numeric channel.", column=column, row=row, timestamp=timestamps.get(row),
                    suggestion="Confirm the column role; if numeric, correct or explicitly select invalid cells to mark missing.", repair={"operation": "drop_invalid_numeric_cells", "columns": [column], "rows": []} if measurement else None)
                continue
            has_bare |= not match[1] and not declared and not row_unit
            try:
                accepted_time = not time_column or row in timestamps
                value, source = _numeric(cell, default, row_unit, target if accepted_time else None)
                if accepted_time:
                    target = target or source
                    sample_time = timestamps.get(row, row)
                    if sample_time not in sample_times:
                        numeric_count += 1
                        sample_times.add(sample_time)
                # Bare unitless values are not explicit unit evidence.
                if match[1] or declared or row_unit:
                    observed[source] += 1
                if value in _SENTINELS:
                    issues.add("possible_sentinel", "warning", "Value resembles a common missing-data sentinel", f"Value {value:g} matches a common export sentinel. It may be a real measurement and is retained unchanged.", column=column, row=row, timestamp=timestamps.get(row), suggestion="Confirm the source's documented sentinel convention; this value is never removed automatically.")
            except ValueError as exc:
                code = "incompatible_units" if "Incompatible units" in str(exc) else ("unsupported_unit" if "Unknown unit" in str(exc) else "invalid_numeric")
                issues.add(code, severity, "Numeric cell or unit is incompatible", str(exc), column=column, row=row, timestamp=timestamps.get(row), suggestion="Correct the source quantity/unit mapping. Units and physical values are not repaired by guessing.",
                    repair={"operation": "drop_invalid_numeric_cells", "columns": [column], "rows": []} if code == "invalid_numeric" and measurement else None)
        if measurement and numeric_count < 2:
            issues.add("insufficient_numeric_samples", "error", "Fewer than two valid numeric samples", "The strict event model requires at least two valid samples per numeric signal.", column=column, count=1, suggestion="Choose category/log/ignore, or supply a capture with sufficient measured samples.")
        if has_bare:
            issues.add("missing_unit", "warning", "Physical source unit is unspecified", "Bare numbers do not establish a physical unit. Name-based candidates require confirmation; otherwise values remain unitless.", column=column, suggestion="Confirm a source unit from the acquisition/export documentation before dimensional comparison.")
        if len(observed) > 1:
            dimensions = {_UNITS[unit]["dimension"] for unit in observed}
            if len(dimensions) == 1:
                issues.add("mixed_unit_scales", "warning", "Compatible units use different scales", f"Explicit source labels include {', '.join(observed)}. The strict importer converts compatible quantities, preserving the original upload.", column=column, count=sum(observed.values()), suggestion="Verify unit labels and preview canonical values before import.")
        proposal = _suggestions(column, header_unit, observed, has_bare, settings["source_units"].get(column))
        if proposal:
            suggestions.append(proposal)
    for issue in issues.entries.values():
        if issue["repair"] and issue["repair"]["operation"] in {"drop_malformed_rows", "drop_invalid_numeric_cells"}:
            issue["repair"]["rows"] = list(issue["rows"])
    return suggestions


def assess_upload(filename, contents, options=None):
    """Return bounded L1 issues for original bytes, including corrupt CSV rows."""
    issues = _Issues()
    try:
        suffix = validate_upload(filename, contents)
    except ValueError as exc:
        issues.add("invalid_upload", "error", "Upload cannot be inspected", str(exc), suggestion="Supply a supported, nonempty upload within the stated bounds.")
        return issues.report()
    if options is not None and not isinstance(options, dict):
        issues.add("invalid_options", "error", "Invalid import options", "Import options must be a JSON object.", suggestion="Correct the options before importing.")
        return issues.report()
    options = options or {}
    if not isinstance(options.get("metadata", {}), dict):
        issues.add("invalid_options", "error", "Invalid metadata mapping", "metadata must be a JSON object.", suggestion="Correct the import metadata before importing.")
        return issues.report()
    if suffix in TABULAR_SUFFIXES:
        data = _read(contents, issues)
        suggestions = _assess_csv(data, options, issues) if data else []
        return issues.report(suggestions)
    try:
        from .service import inspect_upload
        preview = inspect_upload(filename, contents)
        for warning in preview.get("warnings", []):
            issues.add("document_limitation", "warning", "Document extraction limitation", warning, suggestion="Review the preserved source alongside the extracted evidence.")
    except ValueError as exc:
        issues.add("unreadable_document", "error", "Document evidence could not be read", str(exc), suggestion="Export readable UTF-8 text or a text-based, unencrypted PDF; OCR and encoding guesses are not automatic repairs.")
    return issues.report()


def _selection(repair, key, *, required=False):
    values = repair.get(key, [])
    expected = int if key == "rows" else str
    if not isinstance(values, list) or any(isinstance(value, bool) or not isinstance(value, expected) for value in values):
        raise ValueError(f"Repair {key} must be a list of {'physical source row numbers' if key == 'rows' else 'exact column names'}.")
    if required and not values:
        raise ValueError(f"This repair requires explicitly selected {key}.")
    return set(values)


def repair_upload(filename, contents, options, repairs):
    """Apply an explicit whitelist to a CSV copy and return exact change counts.

    Locations always refer to the input's physical source rows, including when
    earlier selected repairs removed/reordered records. Original bytes belong
    to the caller and must be retained with the returned receipt.
    """
    if validate_upload(filename, contents) not in TABULAR_SUFFIXES:
        raise ValueError("Explicit upload repairs support CSV and TSV only; correct other source documents externally.")
    if not isinstance(repairs, list) or len(repairs) > 32:
        raise ValueError("repairs must be a list containing at most 32 explicit operations.")
    if options is not None and not isinstance(options, dict):
        raise ValueError("Import options must be a JSON object.")
    issues = _Issues()
    data = _read(contents, issues)
    if data is None or not data["complete"] or any(issue["code"] in {"empty_header", "duplicate_headers", "csv_syntax", "column_limit", "inspection_limit", "no_data_rows"} for issue in issues.entries.values()):
        raise ValueError("CSV header, syntax, encoding or limits prevent safe repair; correct the source file first.")
    settings = _settings(data, options or {})
    headers, records, changes = data["headers"], data["records"], []
    original_rows = {record["row"] for record in records}
    for repair in repairs:
        if not isinstance(repair, dict):
            raise ValueError("Each repair must be an explicit operation object.")
        if repair.get("operation") and repair.get("action") and repair["operation"] != repair["action"]:
            raise ValueError("Conflicting repair operation/action values.")
        operation = repair.get("operation", repair.get("action"))
        if not isinstance(operation, str) or operation not in _REPAIRS:
            raise ValueError("Unsupported repair operation; filling, interpolation, unit inference and arbitrary edits are prohibited.")
        allowed = {"operation", "action", "rows", "columns", "tokens"}
        if set(repair) - allowed:
            raise ValueError("Unknown repair parameters; only operation, rows, columns and recognized missing tokens are supported.")
        selected_rows = _selection(repair, "rows", required=operation in {"drop_malformed_rows", "drop_invalid_numeric_cells"})
        columns = _selection(repair, "columns", required=operation in {"mark_missing_tokens", "drop_invalid_numeric_cells"})
        if operation in {"drop_exact_duplicate_rows", "drop_malformed_rows"} and columns:
            raise ValueError("Row-removal repairs do not accept column subsets.")
        if "tokens" in repair and operation != "mark_missing_tokens":
            raise ValueError("A missing-token selection is supported only by mark_missing_tokens.")
        if selected_rows - original_rows:
            raise ValueError("Selected repair rows do not identify physical data records in this upload.")
        if columns - set(headers):
            raise ValueError("Selected repair columns do not exist in this upload.")
        locations, changed_rows, count = [], set(), 0
        def changed(record, column=None):
            nonlocal count
            count += 1
            changed_rows.add(record["row"])
            if len(locations) < _EXAMPLES:
                locations.append({"row": record["row"], "end_row": record["end_row"], "column": column})
        if operation == "drop_malformed_rows":
            selected = [record for record in records if record["row"] in selected_rows]
            if any(len(record["cells"]) == len(headers) for record in selected):
                raise ValueError("drop_malformed_rows may exclude only selected records with incorrect field counts.")
            for record in selected:
                changed(record)
            records = [record for record in records if record["row"] not in selected_rows]
        elif operation == "drop_exact_duplicate_rows":
            seen, kept = set(), []
            for record in records:
                key = tuple(record["cells"])
                duplicate = key in seen
                if selected_rows and record["row"] in selected_rows and not duplicate:
                    raise ValueError("Selected duplicate-row repair includes a first occurrence or nonduplicate record.")
                if duplicate and (not selected_rows or record["row"] in selected_rows):
                    changed(record)
                else:
                    kept.append(record)
                seen.add(key)
            records = kept
        elif operation == "sort_by_time":
            if selected_rows or columns:
                raise ValueError("sort_by_time applies to the complete remaining file; row/column subsets are ambiguous.")
            if not settings["time_column"]:
                raise ValueError("sort_by_time requires a measured timestamp column and its confirmed time unit.")
            declared_time = header_details(settings["time_column"])[1]
            if declared_time and declared_time not in TIME_UNITS and "time_unit" not in (options or {}):
                raise ValueError("Explicitly confirm the source time unit before sorting a non-time/unsupported header declaration.")
            if any(len(record["cells"]) != len(headers) for record in records):
                raise ValueError("Explicitly resolve malformed rows before sorting.")
            index = headers.index(settings["time_column"])
            try:
                ordered = sorted(records, key=lambda record: _time(record["cells"][index], settings["time_unit"]))
            except ValueError as exc:
                raise ValueError("Every timestamp must be readable before sorting; timestamps are never filled.") from exc
            for old, new in zip(records, ordered):
                if old is not new:
                    changed(new, settings["time_column"])
            records = ordered
        else:
            if any(settings["roles"].get(column) != "numeric" or column == settings["time_column"] or column in settings["unit_columns"].values() for column in columns):
                raise ValueError("Cell repairs require confirmed numeric measurement columns; text, categorical, unit and timestamp fields are preserved.")
            tokens = repair.get("tokens", sorted(_MISSING))
            if not isinstance(tokens, list) or any(not isinstance(token, str) or token.upper() not in _MISSING for token in tokens):
                raise ValueError("Only recognized NA/N/A/NULL/NaN-style tokens may be marked missing.")
            tokens = {token.upper() for token in tokens}
            for record in records:
                if selected_rows and record["row"] not in selected_rows:
                    continue
                if len(record["cells"]) != len(headers):
                    if record["row"] in selected_rows:
                        raise ValueError("Resolve selected malformed records before cell repairs.")
                    continue
                for column in columns:
                    index, cell = headers.index(column), record["cells"][headers.index(column)].strip()
                    if not cell:
                        continue
                    replace = cell.upper() in tokens
                    if operation == "drop_invalid_numeric_cells":
                        default = settings["source_units"].get(column, header_details(column)[1] or "")
                        unit_column = settings["unit_columns"].get(column)
                        row_unit = record["cells"][headers.index(unit_column)].strip() if unit_column else None
                        try:
                            normalized_default = normalize_unit(default)
                            target = settings["target_units"].get(column) or (normalized_default if default else None)
                            _numeric(cell, normalized_default, row_unit, target)
                            replace = False
                        except ValueError as exc:
                            if "Unknown unit" in str(exc) or "Incompatible units" in str(exc):
                                raise ValueError("Unit errors cannot be repaired by deleting numeric cells; correct the unit mapping/source.") from exc
                            replace = True
                    if replace:
                        record["cells"][index] = ""
                        changed(record, column)
        changes.append({"operation": operation, "count": count, "rows": sorted(changed_rows)[:_EXAMPLES],
            "columns": sorted(columns), "locations": locations, "locations_truncated": count > len(locations)})
    before = hashlib.sha256(contents).hexdigest()
    if any(change["count"] for change in changes):
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=data["delimiter"], lineterminator=data["line_ending"])
        writer.writerow(data["raw_header"])
        retained_rows, ordered_records = {record["row"] for record in records}, iter(records)
        for source_record in data["layout"]:
            if source_record["blank"]:
                writer.writerow(source_record["cells"])
            elif source_record["row"] in retained_rows:
                writer.writerow(next(ordered_records)["cells"])
        result = output.getvalue().encode("utf-8-sig" if data["bom"] else "utf-8")
        if len(result) > MAX_BYTES:
            raise ValueError("Repaired CSV exceeds the 20 MB bound; use a smaller file.")
    else:
        result = contents
    receipt = {"version": "1.0", "stage": "L1", "source_filename": filename,
        "before_checksum": before, "source_checksum": before, "after_checksum": hashlib.sha256(result).hexdigest(),
        "input_rows": len(data["records"]), "output_rows": len(records), "changes": changes,
        "bounds": {"max_bytes": MAX_BYTES, "max_rows": MAX_ROWS, "max_columns": MAX_COLUMNS, "max_cells": MAX_CELLS, "example_locations": _EXAMPLES},
        "notes": ["Original upload must be retained with this receipt.", "No measurements were filled, interpolated or inferred. Source physical row locations identify input records.", "CSV serialization may normalize quoting; untouched text cell contents and the original delimiter are preserved."]}
    return result, receipt
