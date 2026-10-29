"""Friendly clients for mixed-file preview, validation and explicit import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from frib_ds.dashboard.quality_ui import explicit_repair_controls, expectation_controls, render_quality_report, render_unit_suggestions
from frib_ds.dashboard.reset_ui import upload_widget_key
from frib_ds.dashboard.design import empty_state, section_header, workflow_strip


ROLE_LABELS = {"numeric": "Measurement", "category": "Category / state", "log": "Text / log message", "ignore": "Ignore"}
TIME_LABELS = {"s": "Seconds (s)", "ms": "Milliseconds (ms)", "us": "Microseconds (µs)", "ns": "Nanoseconds (ns)", "min": "Minutes", "h": "Hours", "datetime": "Date and time"}


def get_unit_catalog(api_get):
    catalog = st.session_state.get("unit_catalog")
    if catalog is None:
        try:
            catalog = api_get("/units")
            st.session_state["unit_catalog"] = catalog
        except Exception:
            return []
    return catalog


def unit_converter(api_get, api_post, friendly_error, prefix="converter"):
    with st.expander("Convert a measurement unit"):
        catalog = get_unit_catalog(api_get)
        if not catalog:
            st.info("Connect the backend to use the unit converter. Imported units remain visible in the file preview.")
            return
        dimensions = list(dict.fromkeys(row["dimension"] for row in catalog))
        dimension = st.selectbox("Measurement type", dimensions, format_func=lambda value: value.replace("_", " ").title(), key=f"{prefix}_dimension")
        symbols = [row["symbol"] for row in catalog if row["dimension"] == dimension]
        a, b, c = st.columns(3)
        value = a.number_input("Value", value=1.0, format="%.8g", key=f"{prefix}_value")
        source = b.selectbox("From unit", symbols, key=f"{prefix}_from_{dimension}")
        target = c.selectbox("To unit", symbols, index=min(1, len(symbols) - 1), key=f"{prefix}_to_{dimension}")
        if st.button("Convert value", key=f"{prefix}_convert", width="stretch"):
            try:
                result = api_post("/units/convert", {"value": value, "from_unit": source, "to_unit": target})
                st.session_state[f"{prefix}_result"] = result
            except Exception as exc:
                st.error(f"Could not convert the measurement: {friendly_error(exc)}")
        result = st.session_state.get(f"{prefix}_result")
        if result and result.get("value") == value and result.get("from_unit") == source and result.get("to_unit") == target:
            st.success(f"{result['value']:.8g} {result['from_unit']} = {result['converted_value']:.8g} {result['to_unit']}")
        st.caption("Temperature offsets and dimensional compatibility are checked. Unknown or ambiguous units need an explicit correction.")


def _channel_name(column):
    without_unit = re.sub(r"\s*[\[(][^\])]+[\])]\s*$", "", column)
    name = re.sub(r"\s+", "_", without_unit.strip())
    return "PLC_STATE" if name.upper() == "PLC_STATE" else (name.lower() or column)


def _preview_messages(preview):
    if preview.get("preview_notice"):
        st.info(preview["preview_notice"])
    for warning in preview.get("warnings", []):
        st.warning(str(warning))
    validation = preview.get("validation", {})
    for error in validation.get("errors", []):
        st.error(str(error))


def _show_import_summary(summary):
    st.caption(f"Retained {summary.get('retained_rows', '—')} of {summary.get('input_rows', '—')} source rows.")
    counts = st.columns(3)
    counts[0].metric("Measurement channels", summary.get("numeric_signals", 0))
    counts[1].metric("Category records", summary.get("state_changes", 0))
    counts[2].metric("Text records", summary.get("log_entries", 0))
    category_rows = [{"Category": name, "Value": value, "Recorded rows": count} for name, values in summary.get("category_frequencies", {}).items() for value, count in values.items()]
    if category_rows:
        for name, values in summary.get("category_frequencies", {}).items():
            with st.container(border=True):
                st.markdown(f"**{name}**")
                st.caption(" · ".join(f"{value}: {count}" for value, count in list(values.items())[:6]))
        with st.expander("All category counts"):
            st.dataframe(pd.DataFrame(category_rows), width="stretch", hide_index=True)
    severities = summary.get("log_severity_distribution", {})
    if severities:
        st.caption("Log severity: " + " · ".join(f"{level}: {count}" for level, count in severities.items()))
    conversions = summary.get("unit_conversions", [])
    if conversions:
        st.markdown("**Units checked**")
        for conversion in conversions[:8]:
            st.caption(f"{conversion.get('column', 'Measurement')} · {conversion.get('source_unit', 'Source units')} → {conversion.get('target_unit', 'Stored units')} · {conversion.get('count', '—')} entries")
        with st.expander("Full conversion details"):
            st.dataframe(pd.DataFrame(conversions), width="stretch", hide_index=True)
    for note in summary.get("notes", []):
        st.info(str(note))
    st.caption("Counts and source excerpts describe the file contents. They do not establish a physical cause or operating recommendation.")


def mixed_file_importer(kind, api_get, api_post, friendly_error, capture_metadata, navigate_event, show_event_summary, plot_event):
    is_csv = kind == "csv"
    prefix = "csv" if is_csv else "text"
    section_header("Import recorded evidence" if is_csv else "Import narrative evidence",
        "Map measurements, categories and notes, then review the validated capture." if is_csv else
        "Preserve source text with recorded timestamps, severity and explicit states.", kicker="LEVEL 1 / ACQUISITION")
    stages = ["Select source", "Map evidence" if is_csv else "Set context", "Review and save"]
    progress = st.empty()
    with progress.container():
        workflow_strip(stages, active=0)
    example_name = "mixed_units_and_states.csv" if is_csv else "operator_shift.log"
    example = Path(__file__).resolve().parents[3] / "sample_data" / example_name
    quality_example = example.parent / "quality_review.csv"
    with st.container(border=True, key=f"panel_{prefix}_source"):
        st.markdown("**Source file**")
        st.caption("CSV or TSV · UTF-8 · Up to 20 MB. Your original file is preserved." if is_csv else
            "TXT, Markdown, LOG or selectable-text PDF · Up to 20 MB. Scanned pages require OCR before import.")
        upload = st.file_uploader("Choose CSV or TSV" if is_csv else "Choose text or PDF evidence", type=["csv", "tsv"] if is_csv else ["txt", "md", "log", "pdf"], key=upload_widget_key("csv_import" if is_csv else "text_import"))
        if example.is_file() or (is_csv and quality_example.is_file()):
            with st.expander("Example source files"):
                st.caption("Fictional captures for checking the import workflow.")
                if example.is_file():
                    st.download_button("Download a mixed CSV example" if is_csv else "Download a sample shift log", example.read_bytes(), example_name, "text/csv" if is_csv else "text/plain", key=f"{prefix}_example")
                if is_csv and quality_example.is_file():
                    st.download_button("Download an example with quality issues", quality_example.read_bytes(), quality_example.name, "text/csv", key=f"{prefix}_quality_example")
    if not upload:
        empty_state("No source selected", "Choose a file to inspect its quality, confirm the mapping and preview the event before saving.")
        return
    with progress.container():
        workflow_strip(stages, active=1)
    fingerprint = hashlib.sha256(upload.getvalue()).hexdigest()
    identity = f"{upload.name}:{fingerprint}"
    key = f"{prefix}_{fingerprint[:12]}"
    raw_key = f"{key}_source_quality"
    if raw_key not in st.session_state:
        try:
            with st.spinner("Checking the original file…"):
                st.session_state[raw_key] = api_post("/ingestion/quality", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")})
        except Exception:
            st.session_state[raw_key] = None
    raw_quality = st.session_state[raw_key]
    if raw_quality:
        render_quality_report(raw_quality, f"{key}_raw", "Level 1 · Original file quality", expanded=bool(raw_quality.get("issues")))
        render_unit_suggestions(raw_quality)
    else:
        st.info("The source-quality service is unavailable. The import preview will still validate this file; connect the current backend for detailed quality checks.")
        if st.button("Retry source quality check", key=f"{key}_retry_quality"):
            st.session_state.pop(raw_key, None)
            st.rerun()
    repairs = explicit_repair_controls(raw_quality, key)
    if repairs:
        st.info("The original-file findings above remain unchanged. The selected repairs will be applied only to the reviewed import copy and checked below.")
    inspection_options = {"_repairs": repairs} if repairs else {}
    inspection_identity = identity + json.dumps(inspection_options, sort_keys=True)
    cache_key = f"{prefix}_inspection"
    if st.session_state.get(f"{prefix}_inspection_identity") != inspection_identity:
        try:
            with st.spinner("Reading file…"):
                kwargs = {"data": {"options": json.dumps(inspection_options)}} if repairs else {}
                preview = api_post("/ingestion/preview", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}, **kwargs)
            st.session_state[cache_key] = preview
            st.session_state[f"{prefix}_inspection_identity"] = inspection_identity
            st.session_state.pop(f"{prefix}_saved_event_id", None)
            st.session_state.pop(f"{prefix}_saved_options", None)
        except Exception as exc:
            st.error(f"Could not inspect this file: {friendly_error(exc)}")
            return
    preview = st.session_state[cache_key]
    _preview_messages(preview)
    if is_csv and not preview.get("columns") and preview.get("validation", {}).get("valid") is False:
        with progress.container():
            workflow_strip(stages, active=0)
        st.info("Resolve the file-quality issues or select an offered repair above. The repaired copy will be checked again before import.")
        return
    sample = preview.get("sample_rows", [])
    if sample:
        with st.expander("Reviewed import-copy preview" if repairs else "Original file preview", expanded=False):
            st.dataframe(pd.DataFrame(sample), width="stretch", hide_index=True)
    if preview.get("text_preview"):
        with st.expander("Extracted source text", expanded=False):
            st.text_area("Extracted text preview", value=preview["text_preview"], height=180, disabled=True, key=f"{key}_extracted")
    st.caption(f"{upload.name} · {preview.get('row_count', 0):,} source rows / entries · SHA-256 {fingerprint[:16]}…")
    section_header("Capture context", "Name this capture and select the engineering domain. Use General evidence when domain channels are unavailable.", kicker="02 / MAPPING")
    with st.container(border=True, key=f"panel_{prefix}_context"):
        left, right = st.columns(2)
        dataset_name = left.text_input("Dataset name", value=upload.name.rsplit(".", 1)[0], key=f"{key}_name")
        domain = right.selectbox("Engineering domain", ["other", "rf", "mechanical", "plc"], format_func=lambda value: {"other": "General evidence", "rf": "RF / SRF", "mechanical": "Mechanical", "plc": "PLC / Controls"}[value], key=f"{key}_domain")
    metadata = capture_metadata(f"{prefix}_context")
    options = {"dataset_name": dataset_name.strip() or upload.name, "domain": domain, "metadata": metadata, "imported_by": metadata.get("captured_by", "dashboard"), "column_roles": {}, "signal_names": {}, "source_units": {}, "target_units": {}, "unit_columns": {}, "invalid_rows": "reject", "_repairs": repairs}
    catalog = get_unit_catalog(api_get)
    if is_csv:
        columns = preview.get("columns", [])
        names = [column["name"] for column in columns]
        unit_helpers = {column["suggested_unit_column"] for column in columns if column.get("suggested_unit_column")}
        time_options = ["Use row order"] + names
        suggested_time = preview.get("suggested_time_column")
        selected_unit = preview.get("suggested_time_unit") or "row_index"
        with st.container(border=True, key=f"panel_{prefix}_time"):
            st.markdown("**Time axis**")
            st.caption("Choose recorded timestamps when available. Row order preserves sequence without assigning physical timing.")
            time_source, time_format = st.columns(2)
            selected_time = time_source.selectbox("Time column", time_options, index=time_options.index(suggested_time) if suggested_time in names else 0, key=f"{key}_time_column")
            time_unit = time_format.selectbox("Time format / unit", list(TIME_LABELS), index=list(TIME_LABELS).index(selected_unit) if selected_unit in TIME_LABELS else 0, format_func=lambda value: TIME_LABELS[value], key=f"{key}_time_unit", disabled=selected_time == "Use row order")
        options.update(time_column=None if selected_time == "Use row order" else selected_time, time_unit="row_index" if selected_time == "Use row order" else time_unit)
        if selected_time == "Use row order":
            st.info("No measured time axis: entries use unitless row order. Numeric spacing does not establish physical event timing.")
        section_header("What each column means", "Review the suggested roles. Expand a column to change its channel name, meaning or source units.")
        mapping_rows = []
        for column in columns:
            name = column["name"]
            if name == selected_time:
                continue
            column_key = f"{key}_{name}"
            suggested_role = "ignore" if name in unit_helpers else column.get("suggested_role", "ignore")
            current_role = st.session_state.get(f"{column_key}_role", suggested_role)
            current_source = st.session_state.get(f"{column_key}_source_unit", column.get("suggested_unit") or "")
            current_unit_column = st.session_state.get(f"{column_key}_unit_column", column.get("suggested_unit_column"))
            needs_unit_review = current_role == "numeric" and not current_source.strip() and current_unit_column in (None, "Units in header / cells")
            label = f"{name} · {ROLE_LABELS.get(current_role, 'Review role')}"
            if needs_unit_review:
                label += " · Confirm units"
            with st.expander(label, expanded=needs_unit_review):
                st.caption("Source examples: " + ", ".join(str(value) for value in column.get("examples", [])[:3]))
                a, b = st.columns(2)
                role = a.selectbox(f"Role for {name}", list(ROLE_LABELS), index=list(ROLE_LABELS).index(suggested_role) if suggested_role in ROLE_LABELS else 3, format_func=lambda value: ROLE_LABELS[value], key=f"{column_key}_role")
                options["column_roles"][name] = role
                if role != "ignore":
                    options["signal_names"][name] = b.text_input(f"Channel / category name for {name}", value=_channel_name(name), key=f"{column_key}_name").strip() or name
                source_description = "—"
                stored_unit = "—"
                if role == "numeric":
                    c, d = st.columns(2)
                    source_unit = c.text_input(f"Source unit for {name}", value=column.get("suggested_unit") or "", placeholder="Header / cell units, or enter a unit", key=f"{column_key}_source_unit")
                    if source_unit.strip():
                        options["source_units"][name] = source_unit.strip()
                    unit_info = next((row for row in catalog if source_unit.strip() == row["symbol"] or source_unit.strip() in row.get("aliases", [])), None)
                    unit_columns = ["Units in header / cells"] + [candidate for candidate in names if candidate != name]
                    suggested = column.get("suggested_unit_column")
                    unit_column = d.selectbox(f"Per-row unit column for {name}", unit_columns, index=unit_columns.index(suggested) if suggested in unit_columns else 0, key=f"{column_key}_unit_column")
                    if unit_column != unit_columns[0]:
                        options["unit_columns"][name] = unit_column
                    source_description = f"Column: {unit_column}" if unit_column != unit_columns[0] else source_unit.strip() or "Confirm header / cell units"
                    stored_unit = unit_info["canonical_unit"] if unit_info else "Resolved in preview"
                    st.caption(f"Stored unit: {stored_unit}. Source units are checked for compatibility before saving.")
                    if not source_unit.strip() and unit_column == unit_columns[0]:
                        st.caption("For a dimensionless quantity, enter 1 explicitly. Unit hints require your review and are never assigned automatically.")
                elif role == "category":
                    st.caption("Each recorded category or boolean becomes a state record; its source values remain visible.")
                elif role == "log":
                    st.caption("Text is retained as log evidence. A message does not establish a physical diagnosis.")
                else:
                    st.caption("This column is excluded from event records. The original file still preserves it.")
                mapping_rows.append({"Source column": name, "Meaning": ROLE_LABELS[role], "Event channel": options["signal_names"].get(name, "—"), "Source units": source_description, "Stored units": stored_unit})
        if mapping_rows:
            role_counts = {role: sum(row["Meaning"] == label for row in mapping_rows) for role, label in ROLE_LABELS.items()}
            st.caption(f"{role_counts['numeric']} measurements · {role_counts['category']} state channels · {role_counts['log']} note columns · {role_counts['ignore']} ignored")
            with st.expander("All column mappings"):
                st.dataframe(pd.DataFrame(mapping_rows), width="stretch", hide_index=True)
        with st.expander("Advanced import policy"):
            st.caption("Reject invalid entries by default. If you explicitly allow skipping, the preview reports the retained records and skipped counts.")
            skip_invalid = st.checkbox("Skip invalid entries and report counts", value=False, key=f"{key}_skip_invalid", help="Invalid timestamps skip rows; invalid numeric cells skip that measurement. Counts are included; the original remains unchanged.")
        options["invalid_rows"] = "skip" if skip_invalid else "reject"
    numeric_columns = [name for name, role in options["column_roles"].items() if role == "numeric"]
    channel_names = [options["signal_names"].get(name, name) for name in numeric_columns]
    stored_units = {}
    for name in numeric_columns:
        source = options["source_units"].get(name, "")
        info = next((unit for unit in catalog if source == unit["symbol"] or source in unit.get("aliases", [])), None)
        stored_units[options["signal_names"].get(name, name)] = info["canonical_unit"] if info else "unit unresolved"
    options["quality_expectations"] = expectation_controls(channel_names, f"{key}_expect", units=stored_units)
    options_json = json.dumps(options, sort_keys=True)
    validated_key = f"{key}_validated"
    if st.session_state.get(f"{key}_validated_options") != options_json:
        try:
            with st.spinner("Checking columns and units…"):
                validated = api_post("/ingestion/preview", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}, data={"options": options_json, "validate": "true"})
            st.session_state[validated_key] = validated
            st.session_state[f"{key}_validated_options"] = options_json
        except Exception as exc:
            st.error(f"Could not validate the chosen mapping: {friendly_error(exc)}")
            return
    validated = st.session_state[validated_key]
    section_header("Ready-to-save preview", "Review the checked import copy and its quality findings before creating an event.", kicker="03 / VALIDATION")
    _preview_messages(validated)
    quality = validated.get("quality", {})
    if quality.get("l1"):
        render_quality_report(quality["l1"], f"{key}_effective", "Level 1 · Import-copy quality", expanded=bool(repairs))
    if quality.get("l2"):
        render_quality_report(quality["l2"], f"{key}_l2", "Level 2 · Signal quality and expectations", expanded=bool(quality["l2"].get("issues")))
    if validated.get("repair_receipt"):
        with st.expander("Selected repair receipt", expanded=False):
            st.caption("Only the selected operations were applied to the derived copy. Download the original evidence after saving to verify its unchanged bytes.")
            st.json(validated["repair_receipt"])
    for note in dict.fromkeys(validated.get("summary", {}).get("notes", [])):
        if any(phrase in str(note).lower() for phrase in ["no physical unit", "unspecified unit", "unknown unit", "unsupported unit", "missing unit"]):
            st.warning(str(note))
    event = validated.get("event")
    valid = validated.get("validation", {}).get("valid", bool(event)) and st.session_state.get(f"{key}_repairs_valid", True)
    with progress.container():
        workflow_strip(stages, active=2 if valid else 1)
    if event:
        show_event_summary(event)
        if validated.get("summary"):
            with st.expander("Content summary and import details", expanded=False):
                _show_import_summary(validated["summary"])
        plot_event(event, height=350, prefix=f"{key}_preview")
    if valid:
        st.success("Preview is valid. Save once to create the event and preserve the original file.")
    else:
        st.warning("Adjust the mapping or source file to resolve the validation messages before saving.")
    if any(report.get("summary", {}).get("warning", 0) for report in quality.values() if isinstance(report, dict)):
        st.checkbox("I have reviewed the quality warnings", key=f"{key}_reviewed_warnings", help="Optional review note for this session. Warnings may describe a real event and do not by themselves prevent import.")
    already_saved = st.session_state.get(f"{prefix}_saved_options") == f"{identity}:{options_json}"
    if already_saved:
        st.info("This file and mapping have been saved. Open the event below, or change the mapping to create a different event.")
    if st.button("📥 Import dataset" if is_csv else "Save text evidence event", type="primary", disabled=not valid or already_saved, width="stretch", key=f"{key}_commit") and not already_saved:
        try:
            with st.spinner("Saving event and original file…"):
                result = api_post("/ingestion/import", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}, data={"options": options_json})
            saved = result["event"]
            st.session_state["last_imported_event"] = saved
            st.session_state[f"{prefix}_saved_event_id"] = saved["event_id"]
            st.session_state[f"{prefix}_saved_options"] = f"{identity}:{options_json}"
            st.session_state["event_notice"] = f"Saved {saved['event_id']} with its original file. Open the imported event below to inspect evidence and run analysis."
            st.rerun()
        except Exception as exc:
            st.error(f"Could not save the imported event: {friendly_error(exc)}")
    saved_id = st.session_state.get(f"{prefix}_saved_event_id")
    if saved_id:
        st.button("Open imported event in Investigate", on_click=navigate_event, args=(saved_id,), key=f"{key}_open", width="stretch")
