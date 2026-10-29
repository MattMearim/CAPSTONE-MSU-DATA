"""Human-readable quality reports and explicit, reversible import choices."""
from __future__ import annotations

import json
import re
from html import escape

import streamlit as st

from frib_ds.dashboard.design import section_header


def quality_summary_html(report):
    """Compact status and severity counts; issue text remains in native alerts."""
    summary = report.get("summary", {})
    status = str(report.get("status", "review"))
    status_label = {"blocked": "Blocked", "review": "Review required", "ok": "Checks clear"}.get(status, status.replace("_", " ").title())
    tone = {"blocked": "error", "review": "warning", "ok": "ok"}.get(status, "info")
    parts = [f'<div class="quality-summary"><div class="quality-status {tone}"><span>{escape(str(report.get("stage", "Quality")))} · </span><strong>{escape(status_label)}</strong></div>']
    for severity, label in [("error", "Errors"), ("warning", "Warnings"), ("info", "Notes")]:
        parts.append(f'<div class="quality-stat {severity}"><strong>{int(summary.get(severity, 0))}</strong> <small>{label}</small></div>')
    return "".join(parts) + "</div>"


REPAIR_NAMES = {
    "drop_exact_duplicate_rows": "Remove redundant exact duplicate rows",
    "sort_by_time": "Sort complete rows by measured time",
    "mark_missing_tokens": "Mark recognized missing-value tokens as empty",
    "drop_malformed_rows": "Exclude selected malformed rows from the derived copy",
    "drop_invalid_numeric_cells": "Mark selected invalid measurements as empty",
}


def _locations(issue, stage="L1", location_basis=None):
    parts = []
    if issue.get("column"):
        parts.append(f"Column: {issue['column']}")
    rows = issue.get("rows") or []
    if rows:
        row_label = "Sample positions: " if str(stage).upper() == "L2" else "Reviewed-copy rows: " if location_basis == "reviewed_copy_rows" else "Source rows: "
        parts.append(row_label + ", ".join(str(row) for row in rows[:20]) + (" …" if len(rows) > 20 else ""))
    times = issue.get("timestamps_s") or []
    if times:
        parts.append("Time / record coordinates: " + ", ".join(f"{float(value):.6g}" for value in times[:10]) + (" …" if len(times) > 10 else ""))
    if issue.get("count") is not None:
        parts.append(f"Affected entries: {issue['count']}")
    return " · ".join(parts)


def render_quality_report(report, prefix, heading="Data quality review", expanded=False):
    """Render bounded issue details; downloads retain the complete report."""
    if not report:
        st.info("No quality report is available yet. Check the file or saved event to create one.")
        return
    st.markdown(quality_summary_html(report), unsafe_allow_html=True)
    with st.expander(heading, expanded=expanded and report.get("status") == "blocked"):
        if report.get("location_basis") == "reviewed_copy_rows":
            st.caption("Row numbers in this report refer to the reviewed copy. Deletions or sorting can change them; the repair receipt records the original source rows.")
        issues = report.get("issues", [])
        if issues:
            left, right = st.columns([1, 2])
            severities = left.multiselect("Show issue severity", ["error", "warning", "info"], default=["error", "warning", "info"], key=f"{prefix}_severity")
            search = right.text_input("Find an issue or channel", key=f"{prefix}_search", placeholder="Search title, column, message or code").strip().lower()
            visible = [issue for issue in issues if issue.get("severity", "warning") in severities and (not search or search in json.dumps(issue, ensure_ascii=False).lower())]
            show_all = st.checkbox("Show all matching issues", key=f"{prefix}_all_issues") if len(visible) > 3 else False
            limit = 50 if show_all else 3
            st.caption(f"{len(visible)} matching issues · showing {min(len(visible), limit)}")
            for issue in sorted(visible, key=lambda item: {"error": 0, "warning": 1, "info": 2}.get(item.get("severity"), 1))[:limit]:
                severity = issue.get("severity", "warning")
                show = st.error if severity == "error" else st.warning if severity == "warning" else st.info
                with st.container(border=True):
                    show(f"{issue.get('title', issue.get('code', 'Quality flag'))}: {issue.get('message', '')}")
                    if issue.get("suggestion"):
                        st.write(f"Next step: {issue['suggestion']}")
                    with st.expander("Recording interval locations" if issue.get("intervals") else "Source locations"):
                        st.caption(f"{issue.get('code', 'Quality flag')} · {_locations(issue, report.get('stage', 'L1'), report.get('location_basis'))}")
                        if issue.get("intervals"):
                            rows = [{"Start (s)": interval.get("start_s"), "End (s)": interval.get("end_s"),
                                "Observed interval (s)": interval.get("observed_interval_s"),
                                "Expected / reference interval (s)": interval.get("expected_interval_s", interval.get("reference_interval_s")),
                                "Estimated missing positions": interval.get("estimated_missing_samples")}
                                for interval in issue["intervals"][:25]]
                            st.dataframe(rows, width="stretch", hide_index=True)
                            st.caption("These are bounded interval examples. Estimated missing positions are not reconstructed measurements.")
            if not visible:
                st.info("No issues match these filters.")
        else:
            st.success("No issues were found by these checks. Review the source context before drawing engineering conclusions.")
        with st.expander("About these checks"):
            st.caption("Flags describe recorded data and declared expectations. A gap or unusual value may reflect a real event; it does not establish a cause or operator error.")
            st.caption("Locations are bounded examples; affected-entry counts cover the full check. The JSON download contains the report and all its recorded issue details.")
        st.download_button("Download quality report (JSON)", json.dumps(report, indent=2, ensure_ascii=False, default=str), f"{prefix}_quality.json", "application/json", key=f"{prefix}_download", width="stretch")


def explicit_repair_controls(report, prefix):
    """Offer only server-declared whitelist repairs, never apply them by default."""
    st.session_state[f"{prefix}_repairs_valid"] = True
    offered = []
    for issue in (report or {}).get("issues", []):
        repair = issue.get("repair") or {}
        operation = repair.get("operation") or repair.get("action")
        if operation in REPAIR_NAMES:
            item = {**repair, "operation": operation}
            item.pop("action", None)
            if item not in [entry[1] for entry in offered]:
                offered.append((issue, item))
    if not offered:
        return []
    section_header("Optional repairs · your choice", "Every repair creates a derived copy for import. The original upload is preserved unchanged. Select a repair to recheck the preview before saving.", kicker="Explicit changes")
    selected = []
    for index, (issue, repair) in enumerate(offered):
        operation = repair["operation"]
        with st.container(border=True):
            enabled = st.checkbox(REPAIR_NAMES[operation], value=False, key=f"{prefix}_repair_{index}")
            with st.expander("Source locations and repair scope", expanded=enabled):
                st.caption(_locations(issue))
                if operation in {"drop_malformed_rows", "drop_invalid_numeric_cells"}:
                    proposed = repair.get("rows") or issue.get("rows") or []
                    raw_rows = st.text_input("Source row numbers to change", value=", ".join(str(row) for row in proposed), key=f"{prefix}_repair_rows_{index}", disabled=not enabled, help="Physical line numbers from the original file, including its header. Separate numbers with commas.")
                    if enabled:
                        values = [value for value in re.split(r"[,\s]+", raw_rows.strip()) if value]
                        if not values or any(not value.isdigit() or int(value) < 1 for value in values):
                            st.error("Enter explicit positive source row numbers before applying this repair.")
                            st.session_state[f"{prefix}_repairs_valid"] = False
                            continue
                        repair = {**repair, "rows": sorted(set(int(value) for value in values))}
                if repair.get("columns"):
                    st.caption("Columns to change: " + ", ".join(repair["columns"]))
            if enabled:
                selected.append(repair)
    return selected


def render_unit_suggestions(report):
    suggestions = (report or {}).get("unit_suggestions", [])
    if not suggestions:
        return
    with st.expander("Unit hints · confirm against the source"):
        st.caption("These are suggestions, not assigned physical units. Set the source unit or per-row unit column in the mapping below. A channel name alone is not sufficient evidence.")
        for suggestion in suggestions:
            st.markdown(f"**{suggestion.get('column', 'Channel')}**")
            for candidate in suggestion.get("candidates", []):
                st.write(f"{candidate.get('unit', '?')} · {candidate.get('confidence', 'unknown')} confidence")
                for evidence in candidate.get("evidence", [])[:3]:
                    st.caption(str(evidence))


def expectation_controls(channels, prefix, initial=None, units=None):
    """Operator-declared expectations, expressed in the stored physical units."""
    initial, units = initial or {}, units or {}
    with st.expander("Optional quality expectations"):
        st.caption("Declare what this capture should contain. Bounds and stable tolerances use stored units. These checks flag differences; they do not diagnose the equipment.")
        a, b = st.columns(2)
        cadence_enabled = a.checkbox("Check expected sampling interval", value=initial.get("expected_interval_s") is not None, key=f"{prefix}_cadence_enabled")
        cadence = a.number_input("Expected interval (s)", min_value=0.000000001, value=float(initial.get("expected_interval_s") or 1.0), format="%.9g", key=f"{prefix}_cadence", disabled=not cadence_enabled)
        gap_factor = b.number_input("Estimated cadence gap factor", min_value=1.01, value=float(initial.get("gap_factor", 1.8)), step=0.1, key=f"{prefix}_gap_factor", help="Used when cadence is estimated from the recording. With a declared interval, the checks use a 50% timing allowance.")
        expectations = {"gap_factor": gap_factor}
        if cadence_enabled:
            expectations["expected_interval_s"] = cadence
        required = st.text_input("Required channels (optional, separated by commas)", value=", ".join(initial.get("required_channels", [])), key=f"{prefix}_required", help="Use exact channel names. Include absent names if the capture should have contained them.")
        if required.strip():
            expectations["required_channels"] = list(dict.fromkeys(name.strip() for name in required.split(",") if name.strip()))
        channels = list(dict.fromkeys(channels))
        configured = initial.get("channels", {})
        selection_key = f"{prefix}_channels"
        if selection_key in st.session_state:
            st.session_state[selection_key] = [name for name in st.session_state[selection_key] if name in channels]
        selected = st.multiselect("Channels with declared limits or stability", channels, default=[name for name in configured if name in channels], key=selection_key)
        rules = {}
        for name in selected:
            previous = configured.get(name, {})
            unit = units.get(name) or "stored units; confirm source"
            st.markdown(f"**{name} · {unit}**")
            rule = {}
            left, right = st.columns(2)
            lower_enabled = left.checkbox(f"Minimum for {name}", value="min" in previous, key=f"{prefix}_{name}_min_enabled")
            lower = left.number_input(f"Minimum value · {name} ({unit})", value=float(previous.get("min", 0.0)), key=f"{prefix}_{name}_min", disabled=not lower_enabled, format="%.8g")
            upper_enabled = right.checkbox(f"Maximum for {name}", value="max" in previous, key=f"{prefix}_{name}_max_enabled")
            upper = right.number_input(f"Maximum value · {name} ({unit})", value=float(previous.get("max", 1.0)), key=f"{prefix}_{name}_max", disabled=not upper_enabled, format="%.8g")
            if lower_enabled:
                rule["min"] = lower
            if upper_enabled:
                rule["max"] = upper
            channel_cadence = st.checkbox(f"Different expected interval · {name}", value="expected_interval_s" in previous, key=f"{prefix}_{name}_cadence_enabled")
            if channel_cadence:
                rule["expected_interval_s"] = st.number_input(f"Channel interval (s) · {name}", min_value=0.000000001, value=float(previous.get("expected_interval_s", 1.0)), key=f"{prefix}_{name}_cadence", format="%.9g")
            stable = st.checkbox(f"Expected to remain stable · {name}", value=bool(previous.get("expected_stable")), key=f"{prefix}_{name}_stable")
            if stable:
                rule.update(expected_stable=True, stability_tolerance=st.number_input(f"Allowed absolute variation · {name} ({unit})", min_value=0.0, value=float(previous.get("stability_tolerance", 0.0)), key=f"{prefix}_{name}_tolerance", format="%.8g", help="A difference in stored units, not an absolute reading. For temperature stored in K, a 1 K difference equals a 1 °C difference; do not add the temperature offset."))
            check_flatline = st.checkbox(f"Check repeated identical samples · {name}", value="flatline_samples" in previous, key=f"{prefix}_{name}_flatline_enabled")
            if check_flatline:
                rule["flatline_samples"] = st.number_input(f"Identical sample count · {name}", min_value=2, value=int(previous.get("flatline_samples", 10)), step=1, key=f"{prefix}_{name}_flatline")
            if rule:
                rules[name] = rule
        if rules:
            expectations["channels"] = rules
    return expectations


def saved_event_quality(event, api_post, friendly_error, prefix="saved"):
    event_id = event["event_id"]
    key = f"quality_{prefix}_{event_id}"
    stored = event.get("metadata", {}).get("data_quality")
    initial = event.get("metadata", {}).get("quality_expectations") or (stored or {}).get("expectations", {})
    section_header("Capture quality and operator expectations", "Review the original capture, declared limits and any recorded derived-copy repairs.", kicker="Data quality")
    metadata = event.get("metadata", {})
    if metadata.get("upload_quality"):
        if metadata.get("repair_receipt"):
            st.caption("The original-file report is historical: selected repairs produced the reviewed import copy. Original errors do not describe the repaired copy below.")
        render_quality_report(metadata["upload_quality"], f"{key}_original", "Level 1 · Preserved original-file report")
    if metadata.get("effective_upload_quality") and metadata.get("repair_receipt"):
        render_quality_report(metadata["effective_upload_quality"], f"{key}_effective", "Level 1 · Reviewed import-copy report")
        with st.expander("Saved repair receipt"):
            st.json(metadata["repair_receipt"])
    channels = [signal["name"] for signal in event.get("signals", [])]
    units = {signal["name"]: signal.get("unit", "") for signal in event.get("signals", [])}
    expectations = expectation_controls(channels, key, initial, units)
    submitted = st.button("Check saved event quality", key=f"{key}_check", width="stretch")
    if submitted:
        try:
            with st.spinner("Checking recorded data against expectations…"):
                report = api_post(f"/events/{event_id}/quality", {"expectations": expectations})
            st.session_state[key] = {**report, "expectations": expectations}
            st.session_state[f"{key}_expectations"] = expectations
        except Exception as exc:
            st.error(f"Could not check this event: {friendly_error(exc)}")
    report = st.session_state.get(key) or stored
    if report:
        render_quality_report(report, key, "Level 2 · Capture quality report", expanded=True)
        if st.session_state.get(f"{key}_expectations"):
            st.caption("This check uses the submitted expectations and does not change the saved event.")
    else:
        st.info("Check this event to inspect gaps, timestamp consistency and declared limits. Evidence remains unchanged.")
    return report
