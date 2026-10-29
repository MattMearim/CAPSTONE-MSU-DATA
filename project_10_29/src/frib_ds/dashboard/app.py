from __future__ import annotations

import json
import os
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

from frib_ds.dashboard.design import (
    CHART_CONFIG, NAV_LABELS, apply_chart_theme, empty_state, install_design,
    page_header, section_header, workflow_strip, info_card,
)
from frib_ds.dashboard.event_view import render_event_explorer
from frib_ds.dashboard.ingestion_ui import mixed_file_importer, unit_converter
from frib_ds.dashboard.quality_ui import render_quality_report, saved_event_quality
from frib_ds.dashboard.reset_ui import sidebar_project_reset, show_reset_receipt, upload_widget_key
from frib_ds.dashboard.test_lab_ui import render_test_lab
from frib_ds.dashboard.system_ui import render_system_page

API = os.getenv("FRIB_API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="FRIB Decision Support",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Visual system
# -----------------------------------------------------------------------------
install_design()

# -----------------------------------------------------------------------------
# API helpers
# -----------------------------------------------------------------------------
def check_response(response):
    """Keep the server's validation explanation visible to the person using the UI."""
    if response.ok:
        return response
    try:
        detail = response.json().get("detail", response.text)
        if isinstance(detail, list):
            detail = "; ".join(
                f"{'.'.join(str(p) for p in item.get('loc', []) if p != 'body')}: {item.get('msg', item)}"
                for item in detail
            )
    except (ValueError, AttributeError):
        detail = response.text
    raise ValueError(f"{detail or 'The request could not be completed.'} (HTTP {response.status_code})")


def api_get(path: str):
    return check_response(requests.get(API + path, timeout=60)).json()


def api_post(path: str, payload=None, files=None, data=None, timeout=180):
    r = requests.post(API + path, json=payload, files=files, data=data, timeout=timeout)
    return check_response(r).json()


def api_delete(path: str):
    r = requests.delete(API + path, timeout=60)
    return check_response(r).json()


def api_download(path: str) -> bytes:
    return check_response(requests.get(API + path, timeout=60)).content


def safe_api_status():
    try:
        return api_get("/health"), None
    except Exception as exc:
        return None, friendly_error(exc)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "Cannot reach the backend. Open Start FRIB.cmd in the project folder, then press Retry connection."
    if isinstance(exc, requests.Timeout):
        return "The request took too long. Check the backend status in Settings, then try again."
    return str(exc)


def navigate_to(target: str):
    """Switch the main navigation from a normal button callback."""
    st.session_state["main_nav"] = target


def navigate_event(event_id: str):
    st.session_state["investigate_event"] = event_id
    st.session_state["main_nav"] = "🔎 Investigate Event"


def navigate_data(tab: str = "Import data"):
    st.session_state["workspace_tabs"] = tab
    st.session_state["main_nav"] = "🧪 Create Dataset"


def clear_dataset_filters(prefix: str):
    st.session_state[f"{prefix}_search"] = ""
    st.session_state[f"{prefix}_domain"] = "all"


def filter_datasets(rows: list[dict], query: str, domain: str) -> list[dict]:
    query = query.strip().casefold()
    return [row for row in rows if (domain == "all" or row.get("domain") == domain)
            and query in " ".join(str(row.get(key, "")) for key in
                                  ["dataset_name", "event_id", "domain", "event_type"]).casefold()]


def dataset_filters(rows: list[dict], prefix: str) -> list[dict]:
    search_col, domain_col = st.columns([2.4, 1])
    query = search_col.text_input("Find a dataset", placeholder="Search name, event ID, or type", key=f"{prefix}_search")
    domain = domain_col.selectbox("Domain", ["all", *DOMAIN_LABELS],
                                 format_func=lambda value: "All domains" if value == "all" else DOMAIN_LABELS[value],
                                 key=f"{prefix}_domain")
    return filter_datasets(rows, query, domain)


def dataset_table(rows: list[dict], *, compact: bool = False):
    table = pd.DataFrame(rows)
    if "domain" in table:
        table["domain"] = table["domain"].map(lambda value: DOMAIN_LABELS.get(value, value))
    if "event_type" in table:
        table["event_type"] = table["event_type"].map(lambda value: EVENT_TYPE_LABELS.get(value, str(value).replace("_", " ").title()))
    table = table.rename(columns={"dataset_name": "Dataset", "event_id": "Event ID", "domain": "Domain",
                                  "event_type": "Event", "signals": "Signals", "signal_count": "Channels",
                                  "state_count": "Category values", "log_count": "Log entries",
                                  "unit_warning_count": "Unit warnings", "timestamp": "Created"})
    columns = ["Dataset", "Event ID", "Domain", "Created"] if compact else ["Dataset", "Event ID", "Domain", "Event", "Signals", "Category values", "Log entries", "Unit warnings", "Created"]
    st.dataframe(table[[col for col in columns if col in table]], width="stretch", hide_index=True)


def dataset_cards(rows: list[dict], prefix: str, limit: int = 4):
    """Show a bounded, actionable collection without fetching every event."""
    for row in rows[:limit]:
        left, right = st.columns([4, 1], vertical_alignment="center")
        with left:
            domain = DOMAIN_LABELS.get(row.get("domain"), row.get("domain", "Evidence"))
            channels = row.get("signal_count", row.get("signals", 0))
            info_card(row.get("dataset_name") or row["event_id"],
                      f"{channels} channels · {row.get('state_count', 0)} state records · {row.get('log_count', 0)} notes",
                      f"{domain} · {row['event_id']}", "∿")
        right.button("Open", key=f"{prefix}_card_{row['event_id']}", width="stretch",
                     on_click=navigate_event, args=(row["event_id"],))
    if len(rows) > limit:
        st.caption(f"Showing {limit} of {len(rows)} matches. Search to narrow the collection, or choose a dataset below.")


# -----------------------------------------------------------------------------
# Formatting / data utilities
# -----------------------------------------------------------------------------
DOMAIN_LABELS = {
    "rf": "RF / SRF",
    "mechanical": "Mechanical",
    "plc": "PLC / Controls",
    "other": "General evidence",
}

SCENARIO_LABELS = {
    "rf_cavity_trip": "RF Cavity Trip",
    "mechanical_vibration": "Mechanical Vibration Anomaly",
    "plc_interlock": "PLC Interlock Sequence",
}

EVENT_TYPE_LABELS = {
    "cavity_trip": "RF Cavity Trip",
    "vibration_anomaly": "Vibration Anomaly",
    "interlock_sequence": "Interlock Sequence",
    "imported_dataset": "Imported Dataset",
}

SIGNAL_LABELS = {
    "cavity_field": "Cavity Field",
    "forward_power": "Forward Power",
    "reflected_power": "Reflected Power",
    "tuner_pressure": "Tuner Pressure",
    "vibration": "Vibration",
    "bearing_temperature": "Bearing Temperature",
    "process_sensor": "Process Sensor",
}

PARAMETERS = {
    "duration_s": ("Dataset duration", "seconds", "Total simulated time."),
    "sample_rate_hz": ("Sample rate", "Hz", "Samples generated per second."),
    "trip_time_s": ("Trip time", "seconds", "Time when the RF trip occurs."),
    "noise_std": ("Noise level", "", "Amount of random measurement noise."),
    "pressure_rise_start_s": ("Pressure rise starts", "seconds", "When tuner pressure begins rising."),
    "pressure_rise_magnitude": ("Pressure rise amount", "normalized", "Synthetic pressure increase."),
    "reflected_power_rise_start_s": ("Reflected power rise starts", "seconds", "When reflected power begins increasing."),
    "field_decay_tau_s": ("Field decay constant", "seconds", "How quickly the field decays after the trip."),
    "anomaly_time_s": ("Anomaly time", "seconds", "When the mechanical fault begins."),
    "base_frequency_hz": ("Normal vibration frequency", "Hz", "Baseline mechanical vibration frequency."),
    "fault_frequency_hz": ("Fault vibration frequency", "Hz", "Added frequency after the anomaly."),
    "fault_amplitude": ("Fault amplitude", "g", "Strength of the synthetic vibration fault."),
    "warning_time_s": ("Warning time", "seconds", "When PLC state first changes to warning."),
    "interlock_time_s": ("Interlock time", "seconds", "When PLC interlock is latched."),
    "reset_time_s": ("Reset-pending time", "seconds", "When PLC enters reset-pending state."),
}

BASIC_FIELDS = {
    "rf": ["duration_s", "trip_time_s", "noise_std"],
    "mechanical": ["duration_s", "anomaly_time_s", "noise_std"],
    "plc": ["duration_s", "warning_time_s", "interlock_time_s", "reset_time_s"],
}


def event_label(row: dict) -> str:
    name = row.get("dataset_name") or row.get("event_id", "dataset")
    event_type = row.get("event_type", "")
    identifier = f"  ·  {row['event_id']}" if row.get("dataset_name") and row.get("event_id") else ""
    return f"{name}  ·  {DOMAIN_LABELS.get(row.get('domain'), row.get('domain',''))}  ·  {EVENT_TYPE_LABELS.get(event_type, event_type.replace('_', ' ').title())}{identifier}"


def plot_event(event: dict, normalize: bool = False, height: int = 430, prefix: str = "event"):
    report = st.session_state.get(f"quality_saved_{event.get('event_id')}") or event.get("metadata", {}).get("data_quality")
    if report and "expectations" not in report:
        report = {**report, "expectations": event.get("metadata", {}).get("quality_expectations", {})}
    render_event_explorer(event, normalize, height, prefix, SIGNAL_LABELS, quality_report=report)

def show_event_summary(event: dict):
    signals = event.get("signals", [])
    points = sum(len(s.get("values", [])) for s in signals)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Domain", DOMAIN_LABELS.get(event.get("domain"), event.get("domain", "—")))
    c2.metric("Signals", len(signals))
    c3.metric("Data points", f"{points:,}")
    c4.metric("Category values / logs", f"{len(event.get('states', []))} / {len(event.get('logs', []))}")
    normalization = event.get("metadata", {}).get("unit_normalization", {})
    if normalization:
        with st.expander("Units and conversion history", expanded=bool(normalization.get("warnings"))):
            st.caption("This view uses standardized physical units where known. Original source bytes are preserved separately.")
            if normalization.get("signals"):
                st.dataframe(pd.DataFrame(normalization["signals"]), width="stretch", hide_index=True)
            for warning in normalization.get("warnings", []):
                st.warning(warning)


def download_event_buttons(event: dict, prefix: str = "event", context: str = "event"):
    event_id = event.get("event_id")
    key = f"exports_{context}_{event_id}"
    if event.get("metadata", {}).get("repair_receipt"):
        st.info("Event JSON contains the reviewed derived view; download the original source attachment for unchanged bytes. Selected repairs are recorded in the event metadata.")
    if st.button("Prepare original and standardized exports", key=f"{key}_prepare", width="stretch"):
        try:
            st.session_state[key] = {
                "original": api_download(f"/events/{event_id}/download?format=json"),
                "standardized": api_download(f"/events/{event_id}/download?format=normalized-json"),
                "csv": api_download(f"/events/{event_id}/download?format=csv"),
            }
        except Exception as exc:
            st.error(f"Could not prepare the event exports: {friendly_error(exc)}")
    exports = st.session_state.get(key)
    if exports:
        a, b, c = st.columns(3)
        a.download_button("Original event JSON", exports["original"], f"{prefix}_original.json", "application/json", key=f"{key}_original", width="stretch")
        b.download_button("Standardized JSON", exports["standardized"], f"{prefix}_standardized.json", "application/json", key=f"{key}_standardized", width="stretch")
        c.download_button("Standardized CSV", exports["csv"], f"{prefix}_standardized.csv", "text/csv", key=f"{key}_csv", width="stretch")
        st.caption("Standardized exports use common physical units where known. CSV keeps each sample's time and includes category/log rows. Uploaded source files are downloaded separately under Event files.")

def enrich_event_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = dict(row)
        if "dataset_name" in row and "signal_count" in row:
            item["signals"] = row["signal_count"]
            out.append(item)
            continue
        try:
            full = api_get(f"/events/{row['event_id']}")
            item["dataset_name"] = full.get("metadata", {}).get("dataset_name", "")
            item["signals"] = len(full.get("signals", []))
        except Exception:
            item["dataset_name"] = ""
            item["signals"] = ""
        out.append(item)
    return out


def clear_event_state(event_id: str):
    for key in list(st.session_state):
        value = st.session_state[key]
        if event_id in key or (isinstance(value, str) and value == event_id) or (isinstance(value, dict) and value.get("event_id") == event_id):
            del st.session_state[key]
    # Answers can contain event evidence or references to knowledge removed with it.
    st.session_state.pop("corpus_answer", None)


def clear_document_answers():
    for key in list(st.session_state):
        if key == "corpus_answer" or key.startswith("rag_"):
            del st.session_state[key]


def show_sources(sources: list[dict]):
    st.markdown(f"#### Retrieved procedure excerpts ({len(sources)})")
    if not sources:
        st.info("No approved procedure excerpt supports this response. Add approved documents in Procedures.")
        return
    for source in sources:
        label = source.get("label") or source.get("chunk_id", "Source")
        title = source.get("title", "Procedure")
        location = f"Page {source['page']}" if source.get("page") is not None else "Page not recorded"
        revision = source.get("version") or "not recorded"
        with st.expander(f"{label} · {title} · {location} · Revision {revision}"):
            st.caption(f"Document ID: {source.get('document_id', '—')} · Chunk ID: {source.get('chunk_id', '—')}")
            if source.get("section"):
                st.caption(f"Section: {source['section']}")
            st.write(source.get("excerpt") or "No excerpt was provided.")


def show_rag_response(response: dict):
    mode = response.get("mode", "llm")
    if response.get("evidence"):
        st.markdown("#### Recorded / derived event evidence")
        for item in response["evidence"]:
            st.write(item)
    if mode == "extractive":
        st.info("Document search mode: this response quotes retrieved context. No AI interpretation was generated.")
        st.markdown("#### Retrieved guidance")
    elif mode in {"unavailable", "insufficient_context"}:
        st.warning(response.get("error") or "There is not enough approved context to answer this question.")
        st.markdown("#### Search result")
    else:
        st.markdown("#### AI interpretation · requires human review")
        if not response.get("grounded"):
            st.warning("This answer has no verified supporting procedure context. Do not treat it as an operating instruction.")
    st.write(response.get("answer", ""))
    if response.get("interpretation") and response.get("interpretation") != response.get("answer"):
        st.markdown("#### AI interpretation · requires human review")
        st.write(response["interpretation"])
    show_sources(response.get("sources", []))


def show_analysis(analysis: dict, prefix: str):
    st.caption(f"Recorded / derived evidence · Processor: {analysis.get('processor', '—')} · Version: {analysis.get('processor_version', '—')}")
    features = analysis.get("features", {})
    if features.get("data_quality"):
        render_quality_report(features["data_quality"], f"{prefix}_{analysis.get('event_id')}_analysis_quality", "Quality used for this analysis", expanded=bool(features["data_quality"].get("summary", {}).get("error")))
    evidence_summary = features.get("evidence_summary")
    if evidence_summary:
        st.markdown("#### File content summary")
        a, b, c = st.columns(3)
        a.metric("Numeric channels", evidence_summary.get("numeric_channels", 0))
        b.metric("Categorical channels", evidence_summary.get("categorical_channels", 0))
        c.metric("Text records", evidence_summary.get("text_records", 0))
        st.caption(evidence_summary.get("interpretation") or "Descriptive counts and recorded text do not diagnose a cause.")
        category_rows = [{"Category": name, "Value": value["label"], "Recorded occurrences": value["count"]} for name, category in evidence_summary.get("categories", {}).items() for value in category.get("values", [])]
        if category_rows:
            with st.expander("Inspect recorded category counts"):
                st.dataframe(pd.DataFrame(category_rows), width="stretch", hide_index=True)
        severity_counts = evidence_summary.get("log_severity_counts", {})
        if severity_counts:
            st.caption("Recorded log severity: " + " · ".join(f"{level}: {count}" for level, count in severity_counts.items()))
        if evidence_summary.get("text_excerpts"):
            with st.expander("Recorded text excerpts · evidence only"):
                for excerpt in evidence_summary["text_excerpts"]:
                    st.write(excerpt)
    for warning in features.get("warnings", []):
        st.warning(warning)
    if features.get("processing"):
        with st.expander("Cleaning, sampling, and alignment details"):
            st.json(features["processing"])
    feature_rows = [{"feature": name, "value": json.dumps(value) if isinstance(value, (dict, list)) else value} for name, value in features.items()]
    with st.expander("Inspect extracted features"):
        st.dataframe(pd.DataFrame(feature_rows).astype({"value": str}) if feature_rows else pd.DataFrame(columns=["feature", "value"]), width="stretch", hide_index=True)
    st.markdown("#### What the analysis found")
    for finding in analysis.get("findings", []):
        info_card(finding, eyebrow="Derived evidence", symbol="∿")
    if analysis.get("timeline"):
        with st.expander("Follow the reconstructed timeline"):
            for item in analysis["timeline"][:30]:
                coordinate = f"Row {item.get('timestamp_s', '—')}" if features.get("time_basis") == "row_index" else f"{item.get('timestamp_s', '—')} s"
                info_card(item.get("event") or item.get("description") or "Recorded event",
                          str(item.get("evidence", "")), coordinate, "•")
            st.caption("Full timeline values are available in the CSV download.")
    for index, spec in enumerate(analysis.get("plot_specs", [])):
        time_label = spec.get("time_label") or ("Record order (not elapsed time)" if features.get("time_basis") == "row_index" else "Elapsed time (s)")
        if spec.get("kind") == "timeseries" and spec.get("values"):
            series = spec["values"]
            labels = {name: spec.get("labels", {}).get(name) or SIGNAL_LABELS.get(name, name.replace("_", " ").title()) for name in series}
            fig = make_subplots(rows=len(series), cols=1, shared_xaxes=True, subplot_titles=[labels[name] for name in series], vertical_spacing=min(0.08, 0.3 / len(series)))
            for row, (name, values) in enumerate(series.items(), start=1):
                trace = go.Scattergl if len(values) > 3000 else go.Scatter
                fig.add_trace(trace(x=spec.get("timestamps_s", []), y=values, name=labels[name], mode="lines"), row=row, col=1)
                fig.update_yaxes(title_text=f"{labels[name]} ({spec.get('units', {}).get(name) or 'unit not supplied'})", row=row, col=1)
                if spec.get("event_time_s") is not None:
                    fig.add_vline(x=spec["event_time_s"], line_dash="dash", row=row, col=1)
            fig.update_xaxes(title_text=time_label, row=len(series), col=1)
            fig.update_layout(height=max(360, 200 * len(series)), showlegend=False, title=spec.get("title", "Processed / aligned signals"), paper_bgcolor="white", plot_bgcolor="white")
            st.plotly_chart(apply_chart_theme(fig), config=CHART_CONFIG, width="stretch", key=f"{prefix}_aligned_{index}")
        elif spec.get("kind") == "fft" and spec.get("frequencies_hz"):
            fig = go.Figure(go.Scatter(x=spec["frequencies_hz"], y=spec.get("amplitudes", []), mode="lines", name=spec.get("signal", "Spectrum")))
            fig.update_layout(title=spec.get("title", "Frequency spectrum"), xaxis_title="Frequency (Hz)", yaxis_title=f"Amplitude ({spec.get('amplitude_unit') or 'unit not supplied'})", height=330, paper_bgcolor="white", plot_bgcolor="white")
            st.plotly_chart(apply_chart_theme(fig), config=CHART_CONFIG, width="stretch", key=f"{prefix}_fft_{index}")
        elif spec.get("kind") == "scatter" and spec.get("x"):
            fig = go.Figure(go.Scatter(x=spec["x"], y=spec.get("y", []), mode="markers"))
            x_label = spec.get("x_label", "X") + (f" ({spec['x_unit']})" if spec.get("x_unit") else "")
            y_label = spec.get("y_label", "Y") + (f" ({spec['y_unit']})" if spec.get("y_unit") else "")
            fig.update_layout(title=spec.get("title", "Measured trend comparison"), xaxis_title=x_label, yaxis_title=y_label, height=350, paper_bgcolor="white", plot_bgcolor="white")
            st.plotly_chart(apply_chart_theme(fig), config=CHART_CONFIG, width="stretch", key=f"{prefix}_scatter_{index}")
        elif spec.get("kind") == "state_timeline" and spec.get("timestamps_s"):
            messages = spec.get("messages")
            fig = go.Figure(go.Scatter(x=spec["timestamps_s"], y=spec.get("states", []), mode="markers" if messages else "lines+markers", line_shape="hv", text=messages, hovertemplate=f"{time_label}: %{{x}}<br>Recorded value: %{{y}}" + ("<br>%{text}" if messages else "") + "<extra></extra>"))
            fig.update_layout(title=spec.get("title", "Recorded state transitions"), xaxis_title=time_label, yaxis_title=spec.get("state_name", "State") + " (category)", height=330, paper_bgcolor="white", plot_bgcolor="white")
            st.plotly_chart(apply_chart_theme(fig), config=CHART_CONFIG, width="stretch", key=f"{prefix}_states_{index}")
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download analysis JSON", json.dumps(analysis, indent=2, default=str), f"{analysis['event_id']}_analysis.json", "application/json", key=f"{prefix}_analysis_json", width="stretch")
    d2.download_button("Download feature table CSV", pd.DataFrame(feature_rows).to_csv(index=False), f"{analysis['event_id']}_features.csv", "text/csv", key=f"{prefix}_features_csv", width="stretch")
    d3.download_button("Download timeline CSV", pd.DataFrame(analysis.get("timeline", [])).to_csv(index=False), f"{analysis['event_id']}_timeline.csv", "text/csv", key=f"{prefix}_timeline_csv", disabled=not bool(analysis.get("timeline")), width="stretch")


def lines_to_list(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def capture_metadata(prefix: str) -> dict:
    metadata = {}
    with st.expander("Operational context / provenance (optional)"):
        st.caption("Record the context needed to interpret and audit this evidence. Leave fields blank when unknown.")
        for field, label in [("cavity", "Cavity"), ("cryomodule", "Cryomodule"), ("operating_mode", "Operating mode"), ("beam_state", "Beam state"), ("configuration", "Configuration / settings"), ("captured_by", "Captured / imported by")]:
            value = st.text_input(label, key=f"{prefix}_{field}")
            if value.strip():
                metadata[field] = value.strip()
    return metadata


def draft_report(draft: dict) -> str:
    lines = ["# FRIB decision-support report", "", f"Event: {draft.get('event_id')}", f"Draft: {draft.get('draft_id')}", f"Status: {draft.get('status', 'draft')}", f"Generated by: {draft.get('generated_by', '—')}", "", "Human-supervised decision support. No machine-control capability.", "", "## Summary", draft.get("summary", ""), "", "## Recorded / derived observations"]
    lines.extend(f"- {x}" for x in draft.get("observations", []))
    lines.extend(["", "## Interpretation / hypotheses (review required)"])
    for hypothesis in draft.get("hypotheses", []):
        lines.append(f"- {hypothesis.get('rank')}. {hypothesis.get('description')} (support: {hypothesis.get('support', 'unknown')})")
        lines.extend(f"  - Supporting evidence: {x}" for x in hypothesis.get("supporting_evidence", []))
        lines.extend(f"  - Contradicting evidence: {x}" for x in hypothesis.get("contradicting_evidence", []))
    for title, field in [("Suggested actions (human decision required)", "recommended_actions"), ("Affected hardware", "affected_hardware"), ("Source references", "relevant_sources"), ("Tags", "tags")]:
        lines.extend(["", f"## {title}"])
        lines.extend(f"- {x}" for x in draft.get(field, []))
    return "\n".join(lines) + "\n"


def show_draft(draft: dict):
    st.markdown("#### Draft summary / AI interpretation")
    st.info(draft.get("summary", ""))
    st.caption(f"Draft ID: {draft.get('draft_id')} · Status: {draft.get('status', 'draft')} · Generated by: {draft.get('generated_by', '—')}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Recorded / derived observations**")
        for item in draft.get("observations", []):
            st.write("•", item)
        st.markdown("**Suggested actions · human decision required**")
        for item in draft.get("recommended_actions", []):
            st.write("•", item)
        st.markdown("**Affected hardware**")
        st.write(", ".join(draft.get("affected_hardware", [])) or "Not recorded")
    with c2:
        st.markdown("**Interpretation / ranked hypotheses**")
        ranking_method = draft.get("evidence_snapshot", {}).get("hypothesis_ranking_method")
        if ranking_method:
            st.caption(ranking_method)
        for hypothesis in draft.get("hypotheses", []):
            with st.expander(f"#{hypothesis.get('rank')} · {hypothesis.get('description')}"):
                st.write("Support:", hypothesis.get("support"))
                st.write("Supporting evidence:", hypothesis.get("supporting_evidence", []))
                st.write("Contradicting evidence / limitations:", hypothesis.get("contradicting_evidence", []))
        st.markdown("**Procedure / knowledge references**")
        for source in draft.get("relevant_sources", []):
            st.write("•", source)


def review_workspace(event_id: str, prefix: str, analysis_ready: bool):
    st.caption("Read the recorded evidence, procedure excerpts, and interpretation separately. Only an explicit named human decision can create reusable knowledge.")
    try:
        draft = api_get(f"/events/{event_id}/draft")
        st.session_state[f"draft_{event_id}"] = draft
    except Exception as exc:
        if "HTTP 404" in str(exc):
            st.session_state.pop(f"draft_{event_id}", None)
            draft = None
        else:
            draft = st.session_state.get(f"draft_{event_id}")
            st.warning(f"Could not refresh the latest saved draft: {friendly_error(exc)}")
    question = st.text_input("What should the draft focus on?", value="What approved procedural context is relevant to this event?", key=f"{prefix}_question_{event_id}")
    if st.button("Generate new review draft", type="primary", disabled=not analysis_ready, width="stretch", key=f"{prefix}_generate_{event_id}"):
        try:
            draft = api_post(f"/events/{event_id}/draft?question={requests.utils.quote(question)}")
            st.session_state[f"draft_{event_id}"] = draft
        except Exception as exc:
            st.error(f"Could not generate a draft: {friendly_error(exc)}")
    if not draft:
        st.info("Run engineering analysis, then generate a draft to review. Saved drafts will reopen automatically.")
        return
    show_draft(draft)
    d1, d2 = st.columns(2)
    d1.download_button("Download report (.md)", draft_report(draft), f"{draft['draft_id']}_report.md", "text/markdown", key=f"{prefix}_report_{draft['draft_id']}", width="stretch")
    d2.download_button("Download draft JSON", json.dumps(draft, indent=2, default=str), f"{draft['draft_id']}.json", "application/json", key=f"{prefix}_draft_json_{draft['draft_id']}", width="stretch")
    status = draft.get("status", "draft")
    if status != "draft":
        st.success(f"Human decision recorded: {status}. This saved draft cannot be reviewed again. Generate a new draft for a new review.")
        return
    form_key = f"{prefix}_{draft['draft_id']}"
    decision = st.radio("Human decision", ["approve", "correct", "escalate"], horizontal=True, format_func=lambda x: {"approve": "✅ Approve", "correct": "✏️ Correct", "escalate": "⚠️ Escalate"}[x], key=f"{form_key}_decision")
    corrected = None
    if decision == "correct":
        st.markdown("#### Correct the draft")
        st.caption("Use one item per line in the lists. Identifiers and source attribution are preserved.")
        corrected = dict(draft)
        corrected["summary"] = st.text_area("Corrected summary", value=draft.get("summary", ""), key=f"{form_key}_summary")
        for field, label in [("observations", "Corrected observations"), ("recommended_actions", "Corrected actions"), ("affected_hardware", "Affected hardware (one per line)"), ("relevant_sources", "Source references (one retrieved document or knowledge ID per line)"), ("tags", "Tags (one per line)")]:
            corrected[field] = lines_to_list(st.text_area(label, value="\n".join(draft.get(field, [])), key=f"{form_key}_{field}"))
        corrected["hypotheses"] = []
        for index, hypothesis in enumerate(draft.get("hypotheses", [])):
            with st.expander(f"Edit hypothesis {index + 1}", expanded=True):
                edited = dict(hypothesis)
                edited["description"] = st.text_area("Hypothesis description", value=hypothesis.get("description", ""), key=f"{form_key}_hyp_{index}_description")
                edited["support"] = st.text_input("Support level", value=hypothesis.get("support", "unknown"), key=f"{form_key}_hyp_{index}_support")
                for field, label in [("supporting_evidence", "Supporting evidence (one per line)"), ("contradicting_evidence", "Contradicting evidence (one per line)")]:
                    edited[field] = lines_to_list(st.text_area(label, value="\n".join(hypothesis.get(field, [])), key=f"{form_key}_hyp_{index}_{field}"))
                corrected["hypotheses"].append(edited)
        new_hypothesis = st.text_area("Additional hypothesis (optional)", key=f"{form_key}_additional_hypothesis")
        if new_hypothesis.strip():
            corrected["hypotheses"].append({"rank": len(corrected["hypotheses"]) + 1, "description": new_hypothesis.strip(), "support": "unknown", "supporting_evidence": [], "contradicting_evidence": []})
    reviewer = st.text_input("Reviewer full name and role", placeholder="e.g. Jane Smith, RF engineer", key=f"{form_key}_reviewer")
    comments = st.text_area("Review notes", placeholder="Explain the evidence behind this decision or the reason for escalation.", key=f"{form_key}_comments")
    acknowledged = st.checkbox("I reviewed the evidence and source context, and I take responsibility for this decision.", key=f"{form_key}_acknowledged")
    can_submit = bool(reviewer.strip()) and acknowledged and (corrected is None or bool(corrected.get("summary", "").strip()))
    if st.button("Submit human decision", type="primary", disabled=not can_submit, width="stretch", key=f"{form_key}_submit"):
        try:
            api_post(f"/drafts/{draft['draft_id']}/review", {"decision": decision, "reviewer": reviewer.strip(), "comments": comments, "corrected_draft": corrected})
            st.session_state[f"draft_{event_id}"] = api_get(f"/events/{event_id}/draft")
            st.session_state["review_notice"] = "Decision recorded. Approved or corrected results are available in the Knowledge library." if decision != "escalate" else "Escalation recorded. This draft was not added to approved knowledge."
            st.rerun()
        except Exception as exc:
            st.error(f"Could not save the decision: {friendly_error(exc)}")


def document_manager():
    with st.expander("Add procedures · PDF, text, or Markdown"):
      st.caption("Keep the source and revision. Only explicitly approved uploads enter procedure search.")
      with st.form("document_upload_form", clear_on_submit=True):
        uploads = st.file_uploader("Select one or more documents", type=["pdf", "txt", "md"], accept_multiple_files=True, key=upload_widget_key("document_uploads"))
        title = st.text_input("Document title (optional for a single file)", help="When adding several files, each filename becomes its title.")
        version = st.text_input("Version / revision", placeholder="e.g. Rev 3.1")
        approved = st.checkbox("These files are approved for use as procedural guidance", value=False)
        st.caption("Unchecked files are retained for reference with zero indexed chunks; they are excluded from assistant answers.")
        submitted = st.form_submit_button("Add files", type="primary", width="stretch")
    if submitted:
        if not uploads:
            st.warning("Choose at least one file before adding documents.")
        else:
            for upload in uploads:
                try:
                    result = api_post("/documents/index", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}, data={"approved": str(approved).lower(), "title": title.strip() if len(uploads) == 1 and title.strip() else upload.name, "version": version.strip()})
                    st.success(f"Added {upload.name} · {result.get('indexed_chunks', 0)} searchable chunks.")
                except Exception as exc:
                    st.error(f"Could not add {upload.name}: {friendly_error(exc)}")
            clear_document_answers()
    st.subheader("Stored documents")
    try:
        documents = api_get("/documents")
    except Exception as exc:
        st.error(f"Could not load documents: {friendly_error(exc)}")
        return
    search = st.text_input("Find a document", placeholder="Filename, title, revision, or document ID", key="document_search")
    documents = [row for row in documents if search.lower() in " ".join(str(row.get(field, "")) for field in ["filename", "title", "version", "document_id"]).lower()]
    if not documents:
        st.info("No matching documents. Add files above or change your search.")
        return
    table = [{"Filename": row.get("filename"), "Title": row.get("title"), "Revision": row.get("version"), "Approved": row.get("approved", False), "Searchable chunks": row.get("indexed_chunks", 0), "Added": row.get("uploaded_at")} for row in documents]
    for row in documents[:4]:
        info_card(row.get("title") or row.get("filename") or row["document_id"],
                  f"{row.get('version') or 'No revision'} · {row.get('filename', '')}",
                  "Approved reference" if row.get("approved") else "Reference only · excluded from search", "≡")
    with st.expander("Inspect document inventory"):
        st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
    document = st.selectbox("Select a document", documents, format_func=lambda row: f"{row.get('filename', row['document_id'])} · {row.get('version') or 'No revision'} · {row['document_id']}", key="selected_document")
    document_id = document["document_id"]
    with st.expander("Source identity and checksum"):
        st.caption(f"Document ID: {document_id} · Size: {document.get('size_bytes', 0):,} bytes")
        st.code(document.get("checksum") or "Checksum not recorded", language=None)
    download_col, delete_col = st.columns(2)
    with download_col:
        if st.button("Prepare original download", key=f"prepare_document_{document_id}", width="stretch"):
            try:
                st.session_state[f"document_download_{document_id}"] = api_download(f"/documents/{document_id}/download")
            except Exception as exc:
                st.error(f"Could not retrieve this file: {friendly_error(exc)}")
        data = st.session_state.get(f"document_download_{document_id}")
        if data is not None:
            st.download_button("Download original file", data, file_name=document.get("filename") or f"{document_id}.txt", key=f"download_document_{document_id}", width="stretch")
    with delete_col:
        confirm = st.checkbox(f"Delete {document.get('filename', document_id)} and its search index", key=f"confirm_document_{document_id}")
        if st.button("Delete this document", disabled=not confirm, key=f"delete_document_{document_id}", width="stretch"):
            try:
                api_delete(f"/documents/{document_id}")
                clear_document_answers()
                st.session_state.pop(f"document_download_{document_id}", None)
                st.session_state.pop("selected_document", None)
                st.session_state["document_notice"] = "Document and its searchable excerpts deleted. Saved historical review reports keep their source references."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete this document: {friendly_error(exc)}")


def attach_original_source(event_id: str, upload):
    try:
        api_post(f"/events/{event_id}/files", files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")})
        st.success("Original source file preserved with its checksum in the event evidence.")
    except Exception as exc:
        st.warning(f"The event was saved, but its original source file could not be preserved. Add it under Investigation → Evidence → Event files. {friendly_error(exc)}")


def event_file_manager(event_id: str):
    st.markdown("#### Event files")
    st.caption("Preserve original CSV exports, log files, screenshots, and supporting documents with checksums. Attachments remain evidence; they do not enter procedure search.")
    with st.form(f"event_files_form_{event_id}", clear_on_submit=True):
        uploads = st.file_uploader("Add event evidence files", type=["csv", "tsv", "json", "txt", "log", "md", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True, key=upload_widget_key(f"event_files_{event_id}"))
        submitted = st.form_submit_button("Preserve event files", width="stretch")
    if submitted:
        if not uploads:
            st.warning("Choose at least one evidence file.")
        for upload in uploads or []:
            attach_original_source(event_id, upload)
    try:
        files = api_get(f"/events/{event_id}/files")
    except Exception as exc:
        st.error(f"Could not load event files: {friendly_error(exc)}")
        return
    if not files:
        st.info("No original files are attached to this event yet.")
        return
    with st.expander("Inspect attachment inventory and checksums"):
        st.dataframe(pd.DataFrame([{k: row.get(k) for k in ["filename", "size_bytes", "checksum", "uploaded_at"]} for row in files]), width="stretch", hide_index=True)
    selected = st.selectbox("Select an evidence file", files, format_func=lambda row: f"{row['filename']} · {row['file_id']}", key=f"event_file_select_{event_id}")
    file_id = selected["file_id"]
    left, right = st.columns(2)
    with left:
        if st.button("Prepare evidence download", key=f"prepare_event_file_{event_id}_{file_id}", width="stretch"):
            try:
                st.session_state[f"event_file_download_{event_id}_{file_id}"] = api_download(f"/events/{event_id}/files/{file_id}/download")
            except Exception as exc:
                st.error(f"Could not retrieve the file: {friendly_error(exc)}")
        data = st.session_state.get(f"event_file_download_{event_id}_{file_id}")
        if data is not None:
            st.download_button("Download original evidence", data, file_name=selected["filename"], key=f"download_event_file_{event_id}_{file_id}", width="stretch")
    with right:
        confirm = st.checkbox(f"Delete evidence file {selected['filename']}", key=f"confirm_event_file_{event_id}_{file_id}")
        if st.button("Delete this evidence file", disabled=not confirm, key=f"delete_event_file_{event_id}_{file_id}", width="stretch"):
            try:
                api_delete(f"/events/{event_id}/files/{file_id}")
                st.session_state.pop(f"event_file_download_{event_id}_{file_id}", None)
                st.session_state.pop(f"event_file_select_{event_id}", None)
                st.session_state["event_notice"] = "The selected original evidence file was deleted. The stored numeric event data remains available."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete the file: {friendly_error(exc)}")


# -----------------------------------------------------------------------------
# Sidebar / navigation
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">F</div><div><div class="brand-name">FRIB</div><div class="brand-sub">DECISION SUPPORT</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="nav-heading">Workspace</div>', unsafe_allow_html=True)
    page = st.radio("Navigation", list(NAV_LABELS), format_func=lambda value: NAV_LABELS[value],
                    label_visibility="collapsed", key="main_nav", width="stretch")
    st.divider()
    health, health_error = safe_api_status()
    if health:
        st.markdown('<div class="connection"><span class="status-dot"></span>Backend connected</div>', unsafe_allow_html=True)
        st.caption(f"AI: {health.get('llm_provider', '—')} · Search: {health.get('embedding_provider', '—')}")
    else:
        st.markdown('<div class="connection offline"><span class="status-dot"></span>Backend offline</div>', unsafe_allow_html=True)
        st.caption("Open Start FRIB.cmd to start the application.")
    sidebar_project_reset(api_get, api_post, friendly_error)

st.markdown(f'<div class="topbar"><span>FRIB <span aria-hidden="true">/</span> <strong>{escape(NAV_LABELS[page])}</strong></span><span class="topbar-note">Human-supervised decision support</span></div>', unsafe_allow_html=True)
if not health:
    st.warning("Backend is unavailable. Open **Start FRIB.cmd** in the project folder, wait for startup, then retry. Your saved data remains in the project data folder.")
    if st.button("Retry connection", key="global_retry"):
        st.rerun()
elif health.get("llm_provider") in {"mock", "deterministic_fallback"}:
    st.warning("DEMO MODE · AI model not connected. Procedure search and deterministic drafts are available for project validation.")
for notice_key in ["review_notice", "document_notice", "event_notice"]:
    if st.session_state.get(notice_key):
        st.success(st.session_state.pop(notice_key))
show_reset_receipt()

# -----------------------------------------------------------------------------
# HOME
# -----------------------------------------------------------------------------
if page == "🏠 Home":
    page_header("Workspace overview", "From recorded evidence to reviewed engineering knowledge. Start with a dataset or continue an investigation.", "RF / SRF OPERATIONS")
    loaded, load_errors = {}, {}
    for name, endpoint in [("events", "/events"), ("documents", "/documents"), ("knowledge", "/knowledge")]:
        try:
            loaded[name] = api_get(endpoint)
        except Exception as exc:
            loaded[name] = None
            load_errors[name] = friendly_error(exc)
    try:
        counts = api_get("/system/data").get("counts", {})
    except Exception:
        counts = {}

    def overview_count(name):
        return counts.get(name, len(loaded[name])) if loaded[name] is not None else "—"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Datasets", overview_count("events"))
    m2.metric("Procedure files", overview_count("documents"))
    m3.metric("Reviewed knowledge", overview_count("knowledge"))
    m4.metric("Backend", "Connected" if health else "Offline")

    main_col, context_col = st.columns([2.25, 1], gap="large")
    with main_col:
        with st.container(border=True, key="panel_overview_recent"):
            rows = loaded["events"]
            if rows:
                section_header("Recent datasets", "Pick up where you left off.", "L1 · EVIDENCE")
            if rows is None:
                st.error(f"Datasets unavailable: {load_errors['events']}")
                st.button("Retry loading datasets", key="overview_retry")
            elif not rows:
                info_card("Start with a file.", "Import measurements, states, logs, or text. Check quality and units before saving.", "Your workspace is ready", "↑")
                a, b = st.columns(2)
                a.button("Import data", type="primary", width="stretch", key="overview_import", on_click=navigate_data, args=("Import data",))
                b.button("Try a demo dataset", width="stretch", key="overview_generate", on_click=navigate_data, args=("Generate demo",))
                st.caption("Original files stay intact. You review every repair.")
                st.button("Explore ready-made tests", key="overview_lab_quick", on_click=navigate_to, args=("🧰 Test Lab",), width="stretch")
            else:
                filtered = dataset_filters(rows, "overview")
                if not filtered:
                    empty_state("No matching datasets", "Change the search or domain filter to see your stored evidence.")
                    st.button("Clear filters", key="overview_clear_filters", on_click=clear_dataset_filters, args=("overview",))
                else:
                    st.caption(f"{len(filtered)} of {len(rows)} recent datasets shown")
                    dataset_cards(filtered, "overview")
                    with st.expander("Inspect dataset inventory"):
                        dataset_table(filtered, compact=True)
                    ids = [row["event_id"] for row in filtered]
                    if st.session_state.get("overview_event") not in ids:
                        st.session_state.pop("overview_event", None)
                    selected_id = st.selectbox("Dataset to open", ids, key="overview_event", format_func=lambda eid: event_label(next(row for row in filtered if row["event_id"] == eid)))
                    a, b = st.columns(2)
                    a.button("Open investigation", type="primary", width="stretch", key="overview_open", on_click=navigate_event, args=(selected_id,))
                    b.button("Import data", width="stretch", key="overview_import", on_click=navigate_data, args=("Import data",))
                if len(rows) < counts.get("events", 0):
                    st.caption("This view contains the latest 100 datasets. Use the dataset library to manage loaded records.")
    with context_col:
        with st.container(border=True, key="panel_overview_procedures"):
            section_header("Procedure context", "Keep approved references close to the evidence.", "L3 · GUIDANCE")
            documents = loaded["documents"]
            if documents is None:
                st.error(f"Procedure files unavailable: {load_errors['documents']}")
            else:
                approved = sum(bool(row.get("approved")) for row in documents)
                st.markdown(f'<div class="context-card"><b>{approved} approved reference files</b><p>Only approved documents support assistant answers.</p></div>', unsafe_allow_html=True)
            st.button("Manage procedures", width="stretch", key="overview_procedures", on_click=navigate_to, args=("📁 Files & Documents",))
            st.button("Ask the assistant", width="stretch", key="overview_assistant", on_click=navigate_to, args=("💬 Ask Assistant",))
        with st.container(border=True, key="panel_overview_review"):
            section_header("Human decision gate", "Review drafts before they become reusable knowledge.", "L4 · REVIEW")
            if loaded["knowledge"] is None:
                st.error(f"Reviewed knowledge unavailable: {load_errors['knowledge']}")
            st.button("Review results", width="stretch", key="overview_review", on_click=navigate_to, args=("✅ Review Results",))
            st.button("Browse knowledge", width="stretch", key="overview_knowledge", on_click=navigate_to, args=("🧠 Engineering Wiki",))

    section_header("Four levels, one traceable workflow", "Every stage keeps measured evidence, procedural guidance, and interpretation distinguishable.")
    workflow_strip([("Acquire evidence", "Original files + provenance"), ("Process & inspect", "Quality, units + labeled plots"), ("Retrieve guidance", "Approved procedures + sources"), ("Review & publish", "Named human decision")], active=0)
    st.button("Explore the Test Lab", key="overview_test_lab", on_click=navigate_to, args=("🧰 Test Lab",))

# -----------------------------------------------------------------------------
# DATASET STUDIO
# -----------------------------------------------------------------------------
elif page == "🧪 Create Dataset":
    page_header('Data workspace', 'Import evidence, check quality and units, then preserve a validated dataset.', 'L1 · ACQUISITION')

    unit_converter(api_get, api_post, friendly_error, "create_units")
    import_tab, text_tab, json_tab, generate_tab, library_tab = st.tabs(["Import data", "Text & PDF", "Event JSON", "Generate demo", "Dataset library"], key="workspace_tabs", on_change="rerun")

    with generate_tab:
        try:
            generators = api_get("/generators")
        except Exception as exc:
            generators = []
            st.error(f"Could not load generator settings: {exc}")

        if generators:
            by_domain = {g["domain"]: g for g in generators}
            left, right = st.columns([1, 1.25], gap="large")
            with left:
                st.markdown("### 1. Choose a scenario")
                domain = st.selectbox(
                    "Engineering domain",
                    list(by_domain),
                    format_func=lambda x: DOMAIN_LABELS.get(x, x),
                    help="Each domain uses its own synthetic fault model.",
                )
                spec = by_domain[domain]
                defaults = dict(spec.get("defaults", {}))
                scenario_name = SCENARIO_LABELS.get(spec["generator"], spec["generator"].replace("_", " ").title())
                event_type_name = EVENT_TYPE_LABELS.get(spec["event_type"], spec["event_type"].replace("_", " ").title())
                st.info(f"**Scenario:** {scenario_name}  ·  **Event:** {event_type_name}")

                dataset_name = st.text_input("Dataset name", value=f"{scenario_name} Demo", help="A friendly name shown in the dataset library.")
                seed = st.number_input("Random seed", min_value=0, value=42, step=1, help="Use the same seed to reproduce the same synthetic noise. Most users can leave this at 42.")
                generation_metadata = capture_metadata(f"gen_context_{domain}")

                st.markdown("### 2. Adjust the data")
                advanced_mode = st.toggle(
                    "Advanced controls",
                    value=False,
                    help="Turn this on only when you want to change sampling or detailed fault-model parameters.",
                )
                if not advanced_mode:
                    st.caption("Simple mode shows only the settings most users need. Sampling and detailed fault parameters use validated demo defaults.")

                overrides = {}
                basic = BASIC_FIELDS.get(domain, [])
                for key in basic:
                    if key not in defaults:
                        continue
                    label, unit, help_text = PARAMETERS.get(key, (key, "", ""))
                    suffix = f" ({unit})" if unit else ""
                    val = defaults[key]
                    overrides[key] = st.number_input(
                        label + suffix,
                        min_value=0.0,
                        value=float(val),
                        step=0.01 if abs(float(val)) < 10 else 0.1,
                        help=help_text,
                        key=f"gen_{domain}_{key}",
                    )

                # Keep non-visible parameters at their defaults so Simple Mode still produces
                # a complete, reproducible configuration.
                for key, value in defaults.items():
                    if key != "scenario" and isinstance(value, (int, float)) and key not in overrides:
                        overrides[key] = float(value)

                if advanced_mode:
                    st.markdown("#### Advanced scenario settings")
                    st.caption("These values are intended for engineering experiments and validation runs.")
                    advanced_keys = [k for k, v in defaults.items() if k not in basic and k != "scenario" and isinstance(v, (int, float))]
                    for key in advanced_keys:
                        label, unit, help_text = PARAMETERS.get(key, (key.replace("_", " ").title(), "", ""))
                        suffix = f" ({unit})" if unit else ""
                        val = overrides[key]
                        overrides[key] = st.number_input(
                            label + suffix,
                            min_value=0.0,
                            value=float(val),
                            step=1.0 if key == "sample_rate_hz" else (0.01 if abs(float(val)) < 10 else 0.1),
                            help=help_text,
                            key=f"advanced_{domain}_{key}",
                        )

                preset = {"generator": spec["generator"], "seed": int(seed), "dataset_name": dataset_name, "overrides": overrides, "metadata": generation_metadata}
                if advanced_mode:
                    st.download_button(
                        "Save advanced settings as JSON",
                        json.dumps(preset, indent=2),
                        file_name=f"{spec['generator']}_preset.json",
                        mime="application/json",
                        width="stretch",
                    )
                create = st.button("✨ Generate dataset", type="primary", width="stretch")

                if create:
                    try:
                        event = api_post("/events/generate-custom", preset)
                        st.session_state["last_generated_event"] = event
                        st.success(f"Dataset created: {event['event_id']}")
                    except Exception as exc:
                        st.error(f"Could not generate the dataset: {exc}")

            with right:
                st.markdown("### 3. Preview the result")
                event = st.session_state.get("last_generated_event")
                if event:
                    show_event_summary(event)
                    normalize = st.checkbox("Normalize signals for easier visual comparison", value=False, key="gen_norm")
                    plot_event(event, normalize=normalize, prefix="generated")
                    with st.expander("Dataset details"):
                        st.json({"event_id": event.get("event_id"), "metadata": event.get("metadata", {}), "states": event.get("states", []), "logs": event.get("logs", [])})
                    download_event_buttons(event, prefix=event.get("event_id", "dataset"), context="generated")
                else:
                    st.info("Adjust the controls on the left and click **Generate dataset**. Your signal preview will appear here.")

    with import_tab:
        mixed_file_importer("csv", api_get, api_post, friendly_error, capture_metadata, navigate_event, show_event_summary, plot_event)

    with text_tab:
        mixed_file_importer("text", api_get, api_post, friendly_error, capture_metadata, navigate_event, show_event_summary, plot_event)
    with json_tab:
        st.markdown("### Import an event with its provenance")
        st.caption("Use a previously exported FRIB event JSON or a file using the event schema. The supplied event ID, timestamps, states, logs, attachments, and provenance are retained. Existing event IDs cannot be overwritten.")
        json_upload = st.file_uploader("Choose an event JSON file", type=["json"], key=upload_widget_key("json_import"))
        if json_upload:
            try:
                imported_json = json.loads(json_upload.getvalue())
                if not isinstance(imported_json, dict):
                    raise ValueError("The JSON must contain one event object.")
                required = ["event_id", "domain", "event_type", "provenance"]
                missing = [field for field in required if field not in imported_json]
                if missing:
                    raise ValueError("Missing event fields: " + ", ".join(missing))
                st.json({field: imported_json.get(field) for field in ["event_id", "domain", "event_type", "timestamp", "provenance", "metadata"]})
                st.caption(f"Signals: {len(imported_json.get('signals', []))} · State events: {len(imported_json.get('states', []))} · Logs: {len(imported_json.get('logs', []))}")
                if st.button("Import event JSON", type="primary", width="stretch"):
                    result = api_post("/events", imported_json)
                    st.session_state["last_imported_event"] = imported_json
                    st.success(f"Imported event {result['event_id']} with its original provenance.")
                    attach_original_source(result["event_id"], json_upload)
            except Exception as exc:
                st.error(f"Could not import this event: {friendly_error(exc)}")

    with library_tab:
        st.markdown("### Stored datasets")
        st.caption("Open, download, or delete test datasets. Deleting a dataset also removes its derived analysis and knowledge records.")
        try:
            raw_rows = api_get("/events")
            rows = enrich_event_rows(raw_rows)
            library_error = False
        except Exception as exc:
            rows = []
            library_error = True
            st.error(friendly_error(exc))

        if not rows and not library_error:
            st.info("No datasets are stored yet. Generate or import one using the tabs above.")
        elif rows:
            rows = dataset_filters(rows, "library")
            if not rows:
                empty_state("No matching datasets", "Change the search or domain filter to find a stored dataset.")
                st.button("Clear filters", key="library_clear_filters", on_click=clear_dataset_filters, args=("library",))
            else:
                dataset_cards(rows, "library", limit=3)
                with st.expander("Inspect dataset inventory"):
                    dataset_table(rows)
            ids = [row["event_id"] for row in rows]
            if ids:
                if st.session_state.get("library_event") not in ids:
                    st.session_state.pop("library_event", None)
                selected_id = st.selectbox("Select a dataset", ids, key="library_event", format_func=lambda eid: event_label(next(row for row in rows if row["event_id"] == eid)))
                try:
                    selected = api_get(f"/events/{selected_id}")
                except Exception as exc:
                    st.error(f"Could not open the selected dataset: {friendly_error(exc)}")
                    st.stop()
                show_event_summary(selected)
                normalize = st.checkbox("Normalize preview", key="library_norm")
                plot_event(selected, normalize=normalize, height=350, prefix="library")
                download_event_buttons(selected, prefix=selected_id, context="library")
                with st.expander("Delete this dataset"):
                    confirm = st.checkbox("Confirm delete", key=f"confirm_{selected_id}")
                    if st.button("🗑 Delete dataset", disabled=not confirm, width="stretch"):
                        try:
                            api_delete(f"/events/{selected_id}")
                            clear_event_state(selected_id)
                            st.session_state["event_notice"] = "Dataset, derived analysis, drafts, and related knowledge deleted."
                            st.rerun()
                        except Exception as exc:
                            st.error(friendly_error(exc))

# -----------------------------------------------------------------------------
# INVESTIGATE EVENT
# -----------------------------------------------------------------------------
elif page == "🔎 Investigate Event":
    page_header('Event investigation', 'Inspect recorded evidence, derive engineering findings, and review the supporting procedural context.', 'L2 · PROCESSING & VISUALIZATION')
    try:
        events = enrich_event_rows(api_get("/events"))
        st.session_state.pop("investigation_load_error", None)
    except Exception as exc:
        events = []
        st.session_state["investigation_load_error"] = True
        st.error(friendly_error(exc))

    if not events:
        if health and not st.session_state.get("investigation_load_error"):
            empty_state("No dataset selected yet", "Import a dataset to inspect its evidence, quality flags, units, and engineering analysis.")
            st.button("Import a dataset", type="primary", key="investigate_import", on_click=navigate_data)
    else:
        ids = [x["event_id"] for x in events]
        if st.session_state.get("investigate_event") not in ids:
            st.session_state.pop("investigate_event", None)
        eid = st.selectbox("Dataset to investigate", ids, format_func=lambda x: event_label(next(r for r in events if r["event_id"] == x)), key="investigate_event")
        try:
            event = api_get(f"/events/{eid}")
        except Exception as exc:
            st.error(f"Could not open this event: {friendly_error(exc)}")
            st.stop()
        show_event_summary(event)
        evidence_tab, analysis_tab, rag_tab, review_tab = st.tabs(["1 · Evidence", "2 · Analysis", "3 · RAG context", "4 · Human review"])

        with evidence_tab:
            st.subheader("Evidence view · standardized units")
            st.caption("Known physical units are normalized for comparison. Unknown units remain as recorded and are flagged; original files are available below.")
            saved_event_quality(event, api_post, friendly_error)
            normalize = st.checkbox("Normalize signals", key="investigate_norm")
            plot_event(event, normalize=normalize, prefix="investigate")
            with st.expander("Metadata, provenance, states and logs"):
                st.json({"metadata": event.get("metadata", {}), "provenance": event.get("provenance", {}), "states": event.get("states", []), "logs": event.get("logs", [])})
            download_event_buttons(event, prefix=event.get("event_id", "event"), context="investigate")
            event_file_manager(eid)

        with analysis_tab:
            st.subheader("Level 2 · Engineering analysis")
            st.caption("This step derives features and findings from the preserved evidence. It does not approve a cause.")
            if st.button("▶ Run analysis", type="primary", width="stretch"):
                try:
                    expectations = st.session_state.get(f"quality_saved_{eid}_expectations")
                    st.session_state[f"analysis_{eid}"] = api_post(f"/events/{eid}/analyze", {"expectations": expectations}) if expectations else api_post(f"/events/{eid}/analyze")
                    st.success("Analysis completed.")
                except Exception as exc:
                    st.error(friendly_error(exc))
            try:
                analysis = api_get(f"/events/{eid}/analysis")
            except Exception:
                analysis = st.session_state.get(f"analysis_{eid}")
            if analysis:
                show_analysis(analysis, "investigate")
            else:
                st.info("Run Level-2 analysis to populate engineering features and findings.")

        with rag_tab:
            st.subheader("Level 3 · Approved-document assistant")
            st.caption("Answers should come from documents indexed in the approved RAG corpus.")
            q = st.text_area("Question", value="What approved procedural context is relevant to this event?", height=100)
            if st.button("Ask the document assistant", type="primary", width="stretch"):
                try:
                    st.session_state[f"rag_{eid}"] = api_post("/rag/query", {"question": q, "event_id": eid})
                except Exception as exc:
                    st.error(friendly_error(exc))
            rr = st.session_state.get(f"rag_{eid}")
            if rr:
                show_rag_response(rr)

        with review_tab:
            st.subheader("Level 4 · Draft and human decision gate")
            review_workspace(eid, "investigate", bool(analysis))

# -----------------------------------------------------------------------------
# REVIEW RESULTS
# -----------------------------------------------------------------------------
elif page == "✅ Review Results":
    page_header('Human review', 'Review an analyzed event and record a named decision before adding it to trusted knowledge.', 'L4 · KNOWLEDGE GENERATION')
    try:
        review_rows = enrich_event_rows(api_get("/events"))
        review_error = False
    except Exception as exc:
        review_rows = []
        review_error = True
        st.error(f"Could not load events: {exc}")

    if not review_rows and not review_error:
        st.info("There are no datasets to review yet. Import evidence in **Data workspace**, then run an analysis in **Investigation**.")
    elif review_rows:
        chosen = st.selectbox(
            "Choose an event to review",
            review_rows,
            format_func=event_label,
            key="review_event_select",
            help="Only analyzed events can produce a Level-4 draft.",
        )
        review_eid = chosen["event_id"]
        try:
            review_event = api_get(f"/events/{review_eid}")
        except Exception as exc:
            review_event = None
            st.error(f"Could not open this event: {exc}")

        if review_event:
            show_event_summary(review_event)
            try:
                review_analysis = api_get(f"/events/{review_eid}/analysis")
            except Exception:
                review_analysis = None

            if not review_analysis:
                st.warning("This event has not been analyzed yet.")
                if st.button("Run engineering analysis now", type="primary", width="stretch"):
                    try:
                        api_post(f"/events/{review_eid}/analyze")
                        st.success("Analysis completed. You can now generate a review draft.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Analysis failed: {exc}")
            else:
                st.success("Engineering analysis is ready.")
                with st.expander("Recorded / derived evidence", expanded=False):
                    show_analysis(review_analysis, "review")
                review_workspace(review_eid, "review", True)
# -----------------------------------------------------------------------------
# DOCUMENTS & RAG
# -----------------------------------------------------------------------------
elif page == "📁 Files & Documents":
    page_header("Procedure library", "Manage source documents, revisions, and approval for the document-grounded assistant.", "L3 · APPROVED REFERENCES")
    document_manager()

elif page == "💬 Ask Assistant":
    page_header('Procedure assistant', 'Search approved procedures with traceable excerpts. Compare the guidance with recorded evidence.', 'L3 · DOCUMENT-GROUNDED ASSISTANCE')
    st.markdown('<div class="notice"><b>Important:</b> The bundled sample procedures are fictional demo content. Replace them with approved project material before final validation.</div>', unsafe_allow_html=True)
    st.button("Manage procedure files", on_click=navigate_to, args=("📁 Files & Documents",))
    question = st.text_area("Question", height=120, placeholder="Ask a question that should be answered from the approved documents...")
    if st.button("Search approved documents", disabled=not question.strip(), type="primary", width="stretch"):
        try:
            st.session_state["corpus_answer"] = api_post("/rag/query", {"question": question, "event_id": None})
        except Exception as exc:
            st.error(friendly_error(exc))
    answer = st.session_state.get("corpus_answer")
    if answer:
        show_rag_response(answer)

# -----------------------------------------------------------------------------
# KNOWLEDGE BASE
# -----------------------------------------------------------------------------
elif page == "🧠 Engineering Wiki":
    page_header('Knowledge library', 'Find engineering records that passed the human decision gate, with their evidence and review history.', 'L4 · REVIEWED KNOWLEDGE')
    q = st.text_input("Search approved engineering knowledge", placeholder="Search event IDs, findings, hypotheses, tags...")
    try:
        rows = api_get("/knowledge/search?q=" + requests.utils.quote(q)) if q else api_get("/knowledge")
        knowledge_error = False
    except Exception as exc:
        rows = []
        knowledge_error = True
        st.error(friendly_error(exc))
    if not rows and not knowledge_error:
        st.info("No matching approved knowledge records were found.")
    elif rows:
        st.caption(f"{len(rows)} record(s)")
        for row in rows:
            draft = row.get("draft", {})
            title = draft.get("summary", "Approved record")[:100]
            with st.expander(f"✅ {row['event_id']} · {title}"):
                st.markdown("**Human review**")
                review = row.get("review", {})
                st.write(f"Decision: {review.get('decision', '—')} · Reviewer: {review.get('reviewer', '—')} · Reviewed: {review.get('timestamp', '—')}")
                st.write(review.get("comments") or "No review notes recorded.")
                st.markdown("**Reviewed knowledge**")
                show_draft(draft)
                c1, c2 = st.columns(2)
                report = draft_report(draft) + "\n## Human review\n" + f"Decision: {review.get('decision', '—')}\nReviewer: {review.get('reviewer', '—')}\nReviewed: {review.get('timestamp', '—')}\n\n{review.get('comments', '')}\n"
                c1.download_button("Download reviewed report", report, f"{row['knowledge_id']}_report.md", "text/markdown", key=f"wiki_report_{row['knowledge_id']}", width="stretch")
                c2.download_button("Download knowledge JSON", json.dumps(row, indent=2, default=str), f"{row['knowledge_id']}.json", "application/json", key=f"wiki_json_{row['knowledge_id']}", width="stretch")


# -----------------------------------------------------------------------------
# SETTINGS
# -----------------------------------------------------------------------------
elif page == "🧰 Test Lab":
    render_test_lab(api_get, api_post, friendly_error, navigate_event, plot_event, clear_document_answers)

elif page == "🖥️ System & upgrades":
    render_system_page(api_get, api_post, api_delete, friendly_error)

elif page == "⚙️ Settings":
    page_header('Settings', 'Check connected services, convert measurement units, and inspect recorded activity.', 'WORKSPACE ADMINISTRATION')
    current_health, current_error = safe_api_status()
    st.subheader("System status")
    if current_health:
        c1, c2, c3 = st.columns(3)
        c1.metric("Backend", "Connected")
        c2.metric("AI provider", current_health.get("llm_provider", "—"))
        c3.metric("Document search", current_health.get("embedding_provider", "—"))
        st.success("The dashboard can communicate with the backend.")
    else:
        st.error("The application backend is not running yet.")
        st.caption(current_error or "Open Start FRIB.cmd in the project folder and press Retry.")
        if st.button("Retry connection", width="stretch"):
            st.rerun()

    st.subheader("Connection and data")
    st.code(API, language=None)
    st.caption("The one-click launcher starts the backend and dashboard together. Use Data workspace for event data and Procedures for reference files.")
    unit_converter(api_get, api_post, friendly_error, "settings_units")
    st.subheader("Recorded activity")
    try:
        audit = api_get("/audit?limit=100")
        if audit:
            for row in audit[:5]:
                info_card(str(row.get("action", "Activity")).replace("_", " ").title(),
                          str(row.get("entity_id") or "Workspace"), row.get("timestamp", ""), "•")
            with st.expander("Inspect activity table"):
                st.dataframe(pd.DataFrame([{key: row.get(key) for key in ["timestamp", "action", "entity_type", "entity_id"]} for row in audit]), width="stretch", hide_index=True)
            with st.expander("Inspect recorded activity details"):
                activity = st.selectbox("Activity record", audit, format_func=lambda row: f"{row.get('timestamp')} · {row.get('action')} · {row.get('entity_id')}", key="audit_selected")
                st.json(activity)
            st.download_button("Download activity JSON", json.dumps(audit, indent=2, default=str), "frib_activity.json", "application/json", width="stretch")
        else:
            st.info("No activity has been recorded yet.")
    except Exception as exc:
        st.info(f"Activity history is unavailable: {friendly_error(exc)}")

# -----------------------------------------------------------------------------
# HELP
# -----------------------------------------------------------------------------
elif page == "❓ Help":
    page_header('Help & guidance', 'A short guide to importing evidence, investigating events, and recording a human decision.', 'GETTING STARTED')
    st.subheader("From evidence to knowledge")
    st.markdown(
        """
<div class="step"><b>1 · Create Data</b><br><span class="muted">Open Data workspace. Import a file and review its quality and units, or generate a demo dataset.</span></div>
<div class="step"><b>2 · Analyze</b><br><span class="muted">Open Investigation. Select the dataset and run engineering analysis.</span></div>
<div class="step"><b>3 · Ask</b><br><span class="muted">Use Assistant to search the approved procedure library and ask questions.</span></div>
<div class="step"><b>4 · Review</b><br><span class="muted">Open Human review. Read the AI draft and choose Approve, Correct, or Escalate.</span></div>
<div class="step"><b>5 · Save Knowledge</b><br><span class="muted">Approved results appear in the Knowledge library and can help with future events.</span></div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("What the labels mean")
    st.markdown("**📊 Recorded / derived evidence** — measurements, categories, source text and descriptive analysis.  \n**📘 Procedure** — information retrieved from the approved procedure library.  \n**🧠 Reviewed knowledge** — information previously reviewed by a named person.  \n**🤖 AI suggestion** — an interpretation that requires human review.")
    st.info("If something is not working, open **Settings** first. The goal is for errors to be explained in plain language instead of requiring terminal debugging.")




