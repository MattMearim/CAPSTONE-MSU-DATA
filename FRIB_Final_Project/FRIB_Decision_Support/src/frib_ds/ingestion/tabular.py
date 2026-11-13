from __future__ import annotations

from collections import Counter
import csv
import io
from pathlib import Path
import re

import numpy as np

from frib_ds.models import LogEntry, Signal, StateEvent
from frib_ds.units import convert_value, normalize_unit, parse_quantity
from .common import BOOLEAN, MAX_CELLS, MAX_COLUMNS, MAX_ROWS, MAX_SAMPLES, decode_text, make_event, parse_datetime, severity, severity_counts

ROLES = {"numeric", "category", "log", "ignore"}
TIME_UNITS = {"s", "ms", "us", "ns", "min", "h"}
_BARE_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def read_csv(contents):
    text = decode_text(contents)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
    try:
        headers = [name.strip() for name in next(reader)]
        if not headers or not all(headers):
            raise ValueError("CSV columns need nonempty header names.")
        if len(headers) != len(set(headers)):
            raise ValueError("CSV header names must be unique.")
        if len(headers) > MAX_COLUMNS:
            raise ValueError(f"CSV files may contain at most {MAX_COLUMNS} columns.")
        rows, cells = [], 0
        for row in reader:
            if not any(value.strip() for value in row):
                continue
            line = reader.line_num
            if len(row) != len(headers):
                raise ValueError(f"CSV row {line} contains {len(row)} fields; the header contains {len(headers)}.")
            rows.append((line, row))
            cells += len(row)
            if len(rows) > MAX_ROWS or cells > MAX_CELLS:
                raise ValueError("CSV exceeds the limit of 250,000 rows or 1,000,000 cells; import a smaller capture.")
    except StopIteration:
        raise ValueError("The CSV file is empty.") from None
    except csv.Error as exc:
        raise ValueError(f"CSV could not be read: {exc}. Check delimiters, quoting and cell sizes.") from exc
    if not rows:
        raise ValueError("CSV needs a header and at least one data row.")
    return headers, rows, dialect.delimiter


def header_details(header):
    # Avoid regex backtracking over a long, whitespace-heavy uploaded header.
    # A unit declaration occupies the final nonempty bracketed suffix.
    body = header.rstrip()
    if not body or body[-1] not in {']', ')'}:
        return header, None
    closing = body[-1]
    opening = '[' if closing == ']' else '('
    start = body.find(opening, body.rfind(closing, 0, len(body) - 1) + 1)
    if start < 0 or start == len(body) - 2:
        return header, None
    base, declaration = body[:start].strip(), body[start + 1:-1]
    try:
        return base, normalize_unit(declaration)
    except ValueError:
        # Preserve explicit declarations even when unsupported; never silently erase units.
        return base, declaration


def cell_kind(cell, unit=None):
    cell = cell.strip()
    if not cell:
        return "blank"
    if cell.lower() in BOOLEAN:
        return "boolean"
    try:
        parse_quantity(cell, unit or "")
        return "numeric"
    except ValueError:
        return "text"


def profile_csv(headers, rows):
    profiles = []
    time_column, time_unit, warnings = None, "row_index", []
    for index, header in enumerate(headers):
        base, declared_unit = header_details(header)
        if declared_unit is not None:
            try:
                normalize_unit(declared_unit)
            except ValueError:
                warnings.append(f"Column '{header}' declares unsupported unit '{declared_unit}'; select a supported source unit explicitly before numeric import.")
        counts = Counter(cell_kind(row[index], declared_unit) for _, row in rows)
        nonempty = [row[index].strip() for _, row in rows if row[index].strip()]
        unique = list(dict.fromkeys(nonempty))
        role = "ignore"
        suggested_unit = declared_unit
        if nonempty:
            if counts["boolean"] == len(nonempty):
                role = "category"
            elif declared_unit is not None or counts["numeric"] == len(nonempty):
                role = "numeric"
                if suggested_unit is None:
                    try:
                        _, suggested_unit = parse_quantity(nonempty[0])
                        if _BARE_NUMBER.fullmatch(nonempty[0]):
                            suggested_unit = ""
                    except ValueError:
                        suggested_unit = "1"
            elif all(len(value) <= 80 and not re.search(r"\s", value) for value in unique):
                role = "category"
            else:
                role = "log"
        canonical_name = re.sub(r"[^a-z0-9]", "", base.lower())
        if time_column is None and (canonical_name in {"time", "timestamp", "datetime", "date", "t", "elapsed", "times", "timems", "timeus", "timens", "elapsedtime"} or canonical_name.startswith("timestamp")):
            time_column = header
            suffix_unit = next((unit for unit in ("ms", "us", "ns") if canonical_name.endswith("time" + unit) or canonical_name == "time" + unit), None)
            time_unit = declared_unit if declared_unit in TIME_UNITS else (suffix_unit or "s")
            if declared_unit is not None and declared_unit not in TIME_UNITS:
                warnings.append(f"Time column '{header}' declares a non-time or unsupported unit; explicitly choose the correct time unit before import.")
            if nonempty:
                try:
                    parse_datetime(nonempty[0])
                    time_unit = "datetime"
                except ValueError:
                    try:
                        _, observed = parse_quantity(nonempty[0])
                        if observed in TIME_UNITS:
                            time_unit = observed
                    except ValueError:
                        pass
            if time_unit == "s" and declared_unit is None and nonempty:
                try:
                    _, observed = parse_quantity(nonempty[0])
                except ValueError:
                    observed = "1"
                if observed == "1":
                    warnings.append(f"Time column '{header}' has no declared unit; confirm the selected time unit before import.")
        profiles.append({"name": header, "suggested_role": role, "suggested_unit": suggested_unit if suggested_unit is not None else "1",
            "examples": unique[:5], "nonempty_count": len(nonempty),
            "type_counts": {kind: counts[kind] for kind in ("numeric", "boolean", "text", "blank")}})
    numeric = [profile for profile in profiles if profile["suggested_role"] == "numeric" and profile["name"] != time_column]
    for profile in numeric:
        base = re.sub(r"[^a-z0-9]", "", header_details(profile["name"])[0].lower())
        for other in profiles:
            name = re.sub(r"[^a-z0-9]", "", other["name"].lower())
            if name in {base + "unit", base + "units"} or (len(numeric) == 1 and name in {"unit", "units"}):
                profile["suggested_unit_column"] = other["name"]
                break
        if profile["suggested_unit"] == "" and not profile.get("suggested_unit_column"):
            warnings.append(f"Column '{profile['name']}' contains bare numeric values with no declared physical unit; confirm its source unit, or leave it blank to store as unitless without inferring a physical unit.")
    if time_column is None:
        warnings.append("No timestamp column was detected; row-order coordinates are unitless placeholders, not measured seconds.")
    return profiles, time_column, time_unit, warnings


def inspect_csv(filename, contents):
    headers, rows, delimiter = read_csv(contents)
    profiles, time_column, time_unit, warnings = profile_csv(headers, rows)
    return {"filename": filename, "format": "csv", "row_count": len(rows), "delimiter": delimiter,
        "columns": profiles, "sample_rows": [dict(zip(headers, row)) for _, row in rows[:6]],
        "suggested_time_column": time_column, "suggested_time_unit": time_unit, "warnings": warnings}


def mapping(options, key, headers):
    result = options.get(key) or {}
    if not isinstance(result, dict):
        raise ValueError(f"'{key}' must map column names to values.")
    if any(not isinstance(column, str) for column in result):
        raise ValueError(f"'{key}' keys must be column names.")
    unknown = set(result) - set(headers)
    if unknown:
        raise ValueError(f"Unknown columns in '{key}': {', '.join(sorted(unknown))}.")
    return dict(result)


def build_csv(filename, contents, options):
    headers, rows, delimiter = read_csv(contents)
    profiles, suggested_time, suggested_time_unit, notes = profile_csv(headers, rows)
    explicit_roles = mapping(options, "column_roles", headers)
    roles = {profile["name"]: explicit_roles.get(profile["name"], profile["suggested_role"]) for profile in profiles}
    if any(not isinstance(role, str) or role not in ROLES for role in roles.values()):
        raise ValueError("Column roles must be numeric, category, log or ignore.")
    names = mapping(options, "signal_names", headers)
    targets = mapping(options, "target_units", headers)
    sources = mapping(options, "source_units", headers)
    unit_columns = mapping(options, "unit_columns", headers)
    for key, values in (("signal_names", names), ("source_units", sources), ("target_units", targets), ("unit_columns", unit_columns)):
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError(f"'{key}' values must be strings.")
    for profile in profiles:
        if profile.get("suggested_unit_column") and profile["name"] not in unit_columns:
            unit_columns[profile["name"]] = profile["suggested_unit_column"]
    for column in unit_columns.values():
        if column not in headers:
            raise ValueError(f"Unit column '{column}' does not exist in the CSV.")
        if column not in explicit_roles:
            roles[column] = "ignore"
    time_column = options.get("time_column", suggested_time)
    if time_column is not None and not isinstance(time_column, str):
        raise ValueError("'time_column' must be a column name or null.")
    if time_column in {"", "none", "row_index"}:
        time_column = None
    if time_column is not None and time_column not in headers:
        raise ValueError(f"Time column '{time_column}' does not exist in the CSV.")
    if time_column:
        roles[time_column] = "ignore"
    time_unit = options.get("time_unit", suggested_time_unit if time_column else "row_index")
    if not isinstance(time_unit, str) or time_unit not in TIME_UNITS | {"datetime", "row_index"}:
        raise ValueError("Time unit must be s, ms, us, ns, min, h, datetime or row_index.")
    if time_column and "time_unit" not in options:
        declared_time_unit = header_details(time_column)[1]
        if declared_time_unit is not None and declared_time_unit not in TIME_UNITS:
            raise ValueError(f"Time column '{time_column}' has unsupported or non-time unit '{declared_time_unit}'; explicitly choose a supported time_unit.")
    invalid_policy = options.get("invalid_rows", "reject")
    if not isinstance(invalid_policy, str) or invalid_policy not in {"reject", "skip"}:
        raise ValueError("invalid_rows must be reject or skip.")
    if not time_column or time_unit == "row_index":
        time_column, time_unit = None, "row_index"
        message = "Time coordinates use unitless row order; seconds/sample-rate fields are storage placeholders, not measured timing."
        if message not in notes:
            notes.append(message)
    offsets, event_timestamp, invalid_times, naive_seen = [], None, 0, False
    time_index = headers.index(time_column) if time_column else None
    for position, (line, row) in enumerate(rows):
        try:
            if time_index is None:
                timestamp = float(position)
            elif time_unit == "datetime":
                parsed, naive = parse_datetime(row[time_index])
                naive_seen |= naive
                if event_timestamp is None:
                    event_timestamp = parsed
                timestamp = (parsed - event_timestamp).total_seconds()
            else:
                number, unit = parse_quantity(row[time_index], time_unit)
                timestamp = convert_value(number, unit, "s")
            offsets.append((timestamp, line, row))
        except ValueError as exc:
            if invalid_policy == "reject":
                raise ValueError(f"CSV row {line}, time column '{time_column}': {exc}") from exc
            invalid_times += 1
    if not offsets:
        raise ValueError("No rows have a usable timestamp.")
    if naive_seen:
        notes.append("Date/time values without an offset were stored as UTC; verify the source timezone.")
    ordered = sorted(offsets, key=lambda item: item[0])
    if [line for _, line, _ in ordered] != [line for _, line, _ in offsets]:
        notes.append("Rows were ordered by their supplied timestamps for derived signals and state changes; original upload order remains in the preserved file.")
    signals, states, logs, category_frequencies = [], [], [], {}
    conversions = Counter()
    blank_counts, invalid_counts, sample_count = {}, {}, 0
    for index, header in enumerate(headers):
        role = roles[header]
        if role == "ignore":
            continue
        name = names.get(header) or header_details(header)[0]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Choose a nonempty name for column '{header}'.")
        name = name.strip()
        if role == "numeric":
            declared = sources.get(header, header_details(header)[1] or "")
            default_unit = normalize_unit(declared)
            target = normalize_unit(targets[header]) if header in targets else (default_unit if declared else None)
            unit_index = headers.index(unit_columns[header]) if header in unit_columns else None
            times, values, source_symbols, blanks, invalid = [], [], set(), 0, 0
            for timestamp, line, row in ordered:
                cell = row[index].strip()
                if not cell:
                    blanks += 1
                    continue
                try:
                    source_default = row[unit_index].strip() if unit_index is not None and row[unit_index].strip() else default_unit
                    value, source = parse_quantity(cell, source_default)
                    if unit_index is not None and row[unit_index].strip():
                        # Explicit suffixes may differ in scale, but cannot contradict a unit column's dimension.
                        convert_value(value, source, row[unit_index].strip())
                    selected_target = target or source
                    converted = convert_value(value, source, selected_target)
                    if times and timestamp <= times[-1]:
                        raise ValueError("Numeric samples need distinct increasing timestamps; resolve repeated timestamps in the source.")
                except ValueError as exc:
                    if invalid_policy == "reject":
                        raise ValueError(f"CSV row {line}, numeric column '{header}': {exc}") from exc
                    invalid += 1
                    continue
                times.append(timestamp)
                target = selected_target
                values.append(converted)
                source_symbols.add(source)
                if source != target:
                    conversions[(header, source, target)] += 1
            blank_counts[header], invalid_counts[header] = blanks, invalid
            if len(values) < 2:
                raise ValueError(f"Numeric column '{header}' has fewer than two valid samples; choose category/log/ignore or correct the data.")
            sample_count += len(values)
            if sample_count > MAX_SAMPLES:
                raise ValueError("Import exceeds 250,000 numeric samples across all signals; use a smaller capture or ignore columns.")
            if target == "1" and not declared and unit_index is None:
                notes.append(f"Column '{header}' has no physical unit; stored as dimensionless, without inferring a unit from its name.")
            rate = 1.0 / float(np.median(np.diff(times)))
            signals.append(Signal(name=name, unit=target, sample_rate_hz=rate, timestamps_s=times, values=values,
                metadata={"source_column": header, "source_units": sorted(source_symbols), "blank_cells_skipped": blanks,
                    "invalid_cells_skipped": invalid, "inferred_time": time_unit == "row_index"}))
        elif role == "category":
            counts, previous = Counter(), object()
            for timestamp, line, row in ordered:
                value = row[index].strip()
                if not value:
                    continue
                counts[value] += 1
                compare = value.lower() if value.lower() in BOOLEAN else value
                if compare != previous:
                    states.append(StateEvent(timestamp_s=timestamp, name=name, value=value,
                        metadata={"source_column": header, "source_row": line, "inferred_time": time_unit == "row_index"}))
                    previous = compare
            category_frequencies[header] = dict(counts)
        elif role == "log":
            for timestamp, line, row in ordered:
                message = row[index].strip()
                if message:
                    logs.append(LogEntry(timestamp_s=timestamp, level=severity(message), message=message,
                        source=f"{filename}:row {line}:{header}", metadata={"source_column": header, "source_row": line, "inferred_time": time_unit == "row_index"}))
        if len(states) + len(logs) + sample_count > MAX_SAMPLES:
            raise ValueError("Import exceeds 250,000 numeric samples and state/log records combined; use a smaller capture or ignore columns.")
    if not signals and not states and not logs:
        raise ValueError("No evidence columns remain; assign at least one numeric, category or log column.")
    states.sort(key=lambda item: item.timestamp_s)
    logs.sort(key=lambda item: item.timestamp_s)
    summary = {"format": "csv", "input_rows": len(rows), "retained_rows": len(ordered), "invalid_time_rows_skipped": invalid_times,
        "numeric_signals": len(signals), "state_changes": len(states), "log_entries": len(logs),
        "column_roles": roles, "column_types": {profile["name"]: profile["type_counts"] for profile in profiles},
        "category_frequencies": category_frequencies, "log_severity_distribution": severity_counts(logs),
        "blank_numeric_cells_skipped": blank_counts, "invalid_numeric_cells_skipped": invalid_counts,
        "unit_conversions": [{"column": column, "source_unit": source, "target_unit": target, "count": count} for (column, source, target), count in conversions.items()],
        "time_basis": time_unit, "time_column": time_column, "delimiter": delimiter, "notes": list(dict.fromkeys(notes))}
    return make_event(filename, contents, options, signals, states, logs, summary, event_timestamp)
