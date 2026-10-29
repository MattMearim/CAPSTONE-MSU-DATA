"""Interactive evidence views, preserving each channel's time grid and unit."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from frib_ds.dashboard.design import CHART_CONFIG, CHART_PALETTE, apply_chart_theme, section_header


SIGNAL_COLORS = tuple(CHART_PALETTE)
SEVERITY_COLORS = {"ERROR": "#b4232c", "CRITICAL": "#b4232c", "FATAL": "#b4232c",
    "WARNING": "#b77913", "WARN": "#b77913", "INFO": "#087f8c", "DEBUG": "#627585", "TRACE": "#627585"}


def chart_config(filename="recorded_evidence"):
    return {**CHART_CONFIG, "displayModeBar": True,
        "toImageButtonOptions": {**CHART_CONFIG["toImageButtonOptions"], "filename": filename}}


def _keep_evidence_kind(key, default):
    if st.session_state.get(key) is None:
        st.session_state[key] = default


def signal_figure(signals, labels, window, normalize=False, title="Measured signals", height=430, time_label="Elapsed time (s)", quality_report=None):
    """Keep unlike measurements on separate labeled axes, even when normalized."""
    fig = make_subplots(rows=len(signals), cols=1, shared_xaxes=True,
        subplot_titles=[escape(labels[signal["name"]]) for signal in signals],
        vertical_spacing=min(0.08, 0.3 / len(signals)))
    for row, signal in enumerate(signals, start=1):
        times = np.asarray(signal.get("timestamps_s", []), dtype=float)
        values = np.asarray(signal.get("values", []), dtype=float)
        with np.errstate(over="ignore", invalid="ignore"):
            source_steps = np.diff(times)
        positive_steps = np.sort(source_steps[np.isfinite(source_steps) & (source_steps > 0)])
        mask = (times >= window[0]) & (times <= window[1])
        times, values = times[mask], values[mask]
        unit = signal.get("unit") or "unit not supplied"
        if normalize and values.size:
            magnitude = float(np.max(np.abs(values)))
            scaled = values / magnitude if magnitude else values
            std = scaled.std()
            values = (scaled - scaled.mean()) / (std if std > 0 else 1.0)
            unit = "standard deviations"
        label = labels[signal["name"]]
        expectations = (quality_report or {}).get("expectations", {})
        rule = expectations.get("channels", {}).get(signal["name"], {})
        expected = rule.get("expected_interval_s") or expectations.get("expected_interval_s")
        midpoint = len(positive_steps) // 2
        typical = float(positive_steps[midpoint]) if len(positive_steps) % 2 else float(positive_steps[midpoint - 1] / 2 + positive_steps[midpoint] / 2) if positive_steps.size else None
        baseline = float(expected) if expected else typical
        gap_factor = 1.5 if expected else float(expectations.get("gap_factor", 1.8))
        downsampled = signal.get("metadata", {}).get("preview_total_samples", len(signal.get("values", []))) > len(signal.get("values", []))
        inferred_time = signal.get("metadata", {}).get("inferred_time") is True or any(label in time_label.lower() for label in ["row order", "record order", "not measured", "not elapsed"])
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            gaps = set(int(index) for index in np.where(np.diff(times) / baseline >= gap_factor)[0]) if baseline and not downsampled and not inferred_time else set()
        intervals = [interval for issue in (quality_report or {}).get("issues", []) if issue.get("column") == signal["name"] for interval in issue.get("intervals", []) if interval.get("start_s") is not None and interval.get("end_s") is not None]
        if intervals:
            gaps.update(int(index) for interval in intervals for index in np.where((times[:-1] < float(interval["end_s"])) & (times[1:] > float(interval["start_s"])))[0])
        display_times, display_values = times.tolist(), values.tolist()
        ordered_gaps = sorted(gaps)
        for index in reversed(ordered_gaps):
            display_times.insert(int(index) + 1, None)
            display_values.insert(int(index) + 1, None)
            if not intervals and index in ordered_gaps[:25]:
                fig.add_vrect(x0=float(times[index]), x1=float(times[index + 1]), fillcolor="#fef3c7", opacity=0.5, line_width=0, row=row, col=1, exclude_empty_subplots=False)
        for interval in intervals:
            start, end = max(window[0], float(interval["start_s"])), min(window[1], float(interval["end_s"]))
            if end > start:
                fig.add_vrect(x0=start, x1=end, fillcolor="#fef3c7", opacity=0.5, line_width=0, row=row, col=1, exclude_empty_subplots=False)
        trace = go.Scattergl if len(times) > 3000 else go.Scatter
        color = SIGNAL_COLORS[(row - 1) % len(SIGNAL_COLORS)]
        fig.add_trace(trace(x=display_times, y=display_values, mode="markers" if downsampled else "lines", name=label, connectgaps=False,
            line=dict(color=color, width=1.8), marker=dict(color=color, size=5),
            hovertemplate=f"{escape(label)}<br>{escape(time_label)}: %{{x:.6g}}<br>Value: %{{y:.6g}} {escape(unit)}<extra></extra>"), row=row, col=1)
        flagged = []
        for issue in (quality_report or {}).get("issues", []):
            if issue.get("column") not in {signal["name"], None} or issue.get("severity") not in {"error", "warning"}:
                continue
            for timestamp in issue.get("timestamps_s", [])[:100]:
                matches = np.where(np.isclose(times, float(timestamp), rtol=0, atol=1e-9))[0]
                if matches.size:
                    index = int(matches[0])
                    flagged.append((float(times[index]), float(values[index]), issue.get("title") or issue.get("code", "Quality flag"), issue.get("severity")))
        if flagged:
            fig.add_trace(go.Scatter(x=[point[0] for point in flagged], y=[point[1] for point in flagged], text=[escape(point[2]) for point in flagged], mode="markers", name="Quality flag", marker=dict(color=["#b4232c" if point[3] == "error" else "#b77913" for point in flagged], size=8, symbol="diamond-open", line=dict(width=1.5)), hovertemplate="%{text}<br>Coordinate: %{x:.6g}<br>Recorded value: %{y:.6g}<extra></extra>"), row=row, col=1)
        fig.update_yaxes(title_text=f"{escape(label)}<br>({escape(unit)})", row=row, col=1)
    fig.update_xaxes(title_text=time_label, row=len(signals), col=1)
    apply_chart_theme(fig, height=max(height, 210 * len(signals)))
    fig.update_layout(title=title, showlegend=False, hovermode="x unified", margin=dict(l=60, r=24, t=78, b=48))
    fig.update_xaxes(range=list(window))
    fig.update_annotations(font=dict(size=12, color="#182632"))
    return fig


def render_event_explorer(event, normalize=False, height=430, prefix="event", default_labels=None, quality_report=None):
    """Show one kind of evidence at a time, with source detail on demand."""
    signals, states, logs = event.get("signals", []), event.get("states", []), event.get("logs", [])
    if not (signals or states or logs):
        st.info("No evidence to show yet. Add a file or import a capture to get started.")
        return
    defaults = default_labels or {}
    event_id = event.get("event_id", "preview")
    row_order = event.get("metadata", {}).get("import_summary", {}).get("time_basis") == "row_index"
    time_label = "Row order (timing not measured)" if row_order else "Elapsed time (s)"
    key = f"view_{prefix}_{event_id}"
    times = [float(t) for signal in signals for t in signal.get("timestamps_s", [])]
    times.extend(float(row.get("timestamp_s", 0)) for row in states + logs)
    minimum, maximum = (min(times), max(times)) if times else (0.0, 0.0)
    labels = {signal["name"]: signal.get("metadata", {}).get("display_label") or defaults.get(signal["name"], signal["name"].replace("_", " ").title()) for signal in signals}
    available = [name for name, entries in [("Signals", signals), ("States", states), ("Notes", logs)] if entries]
    section_header("Explore the evidence", "Choose what to look at. Your original capture stays unchanged.")
    if not signals:
        st.caption("No numeric channels in this capture. Explore the recorded states and notes below.")
    selection_key = f"{key}_kind"
    if st.session_state.get(selection_key) not in available:
        st.session_state.pop(selection_key, None)
    kind = st.segmented_control("Evidence view", available, default=available[0], key=selection_key, label_visibility="collapsed", on_change=_keep_evidence_kind, args=(selection_key, available[0])) if len(available) > 1 else available[0]
    kind = kind or available[0]
    with st.expander("Time range", expanded=False):
        if maximum > minimum:
            window = st.slider(f"Visible window · {time_label}", min_value=minimum, max_value=maximum, value=(minimum, maximum), key=f"{key}_window")
        else:
            window = (minimum, maximum)
        if event.get("metadata", {}).get("import_summary", {}).get("time_basis") == "datetime":
            st.caption(f"Elapsed-time origin: {event.get('timestamp', 'recorded event timestamp')}")
    st.caption(f"{window[0]:.6g}–{window[1]:.6g} {'in record order' if row_order else 'seconds'} · {len(signals)} signal channels · {len(states)} state records · {len(logs)} notes")

    if kind == "Signals":
        signal_names = [signal["name"] for signal in signals]
        # Keep option serialization stable while editable chart labels change below.
        selection_labels = dict(labels)
        remembered = st.session_state.get(f"{key}_saved_signals", signal_names[:3])
        chosen = st.multiselect("Visible numeric channels", signal_names, default=[name for name in remembered if name in signal_names], format_func=lambda name: selection_labels[name], key=f"{key}_signals")
        st.session_state[f"{key}_saved_signals"] = chosen
        remembered_labels = st.session_state.get(f"{key}_saved_labels", {})
        with st.expander("Chart title and display labels"):
            title = st.text_input("Chart title", value=st.session_state.get(f"{key}_saved_title", f"{event.get('metadata', {}).get('dataset_name') or event_id} · Measured signals"), key=f"{key}_title")
            st.session_state[f"{key}_saved_title"] = title
            for name in chosen:
                labels[name] = st.text_input(f"Display label for {name}", value=remembered_labels.get(name, labels[name]), key=f"{key}_label_{name}").strip() or labels[name]
                remembered_labels[name] = labels[name]
        st.session_state[f"{key}_saved_labels"] = remembered_labels
        if not chosen:
            st.info("Select a numeric channel above to show its waveform.")
            return
        displayed = [signal for signal in signals if signal["name"] in chosen]
        if not any(any(window[0] <= float(t) <= window[1] for t in signal.get("timestamps_s", [])) for signal in displayed):
            st.info("No samples in this range. Widen the time range to see the capture.")
            return
        quality_report = quality_report or event.get("metadata", {}).get("data_quality")
        fig = signal_figure(displayed, labels, window, normalize, title, height, time_label, quality_report)
        truth = event.get("metadata", {}).get("synthetic_ground_truth", {}) or {}
        for field, marker in [("trip_time_s", "Synthetic trip"), ("anomaly_time_s", "Synthetic anomaly"), ("warning_time_s", "Synthetic warning"), ("interlock_time_s", "Synthetic interlock"), ("reset_time_s", "Synthetic reset pending")]:
            if field in truth and window[0] <= float(truth[field]) <= window[1]:
                fig.add_vline(x=float(truth[field]), line_dash="dash", annotation_text=marker, row=1, col=1)
        st.plotly_chart(fig, width="stretch", key=f"{key}_numeric_chart", config=chart_config(f"{event_id}_signals"))
        reduced = any(signal.get("metadata", {}).get("preview_total_samples", len(signal.get("values", []))) > len(signal.get("values", [])) for signal in displayed)
        if reduced:
            st.caption("Reduced preview · observed samples only; connecting lines are omitted.")
        with st.expander("How to read this chart"):
            st.caption("Each channel has its own unit axis. Shading shows bounded gap examples; full-data lines stop at every interval above the applied cadence threshold. Diamonds identify quality flags at recorded coordinates.")
            st.caption("Reduced previews show observed sample markers. Omitted samples do not imply a continuous recording. Labels, normalization and time filters change this view only.")
        return

    if kind == "States":
        names = list(dict.fromkeys(row.get("name", "Category") for row in states))
        remembered = st.session_state.get(f"{key}_saved_categories", names[:3])
        selected_names = st.multiselect("Visible categories / states", names, default=[name for name in remembered if name in names], key=f"{key}_categories")
        st.session_state[f"{key}_saved_categories"] = selected_names
        remembered_labels = st.session_state.get(f"{key}_saved_category_labels", {})
        category_labels = {}
        with st.expander("Category display labels"):
            for name in selected_names:
                category_labels[name] = st.text_input(f"Display label for category {name}", value=remembered_labels.get(name, name), key=f"{key}_category_label_{name}").strip() or name
                remembered_labels[name] = category_labels[name]
        st.session_state[f"{key}_saved_category_labels"] = remembered_labels
        if not selected_names:
            st.info("Choose a state channel to see its recorded values.")
        for name in selected_names:
            entries = sorted((row for row in states if row.get("name") == name and window[0] <= float(row.get("timestamp_s", 0)) <= window[1]), key=lambda row: row["timestamp_s"])
            if not entries:
                st.caption(f"{name}: no state records in this range.")
                continue
            distinct = list(dict.fromkeys(str(row.get("value", "")) for row in entries))
            st.caption(f"{category_labels[name]} · {len(entries)} records · {len(distinct)} distinct values")
            fig = go.Figure(go.Scatter(x=[row["timestamp_s"] for row in entries], y=[str(row.get("value", "")) for row in entries], mode="lines+markers", line_shape="hv", line=dict(color=SIGNAL_COLORS[0], width=1.8), marker=dict(color=SIGNAL_COLORS[0], size=6), hovertemplate=f"{time_label}: %{{x:.6g}}<br>Category: %{{y}}<extra></extra>"))
            apply_chart_theme(fig, height=280)
            fig.update_layout(title=category_labels[name], xaxis_title=time_label, yaxis_title=f"{category_labels[name]} (category)", showlegend=False)
            st.plotly_chart(fig, width="stretch", key=f"{key}_category_chart_{name}", config=chart_config(f"{event_id}_categories"))
            with st.expander(f"Recorded values · {name}"):
                st.dataframe(pd.DataFrame(entries), width="stretch", hide_index=True)
        return

    levels = list(dict.fromkeys(str(row.get("level", "INFO")) for row in logs))
    left, right = st.columns([1, 2])
    remembered_levels = st.session_state.get(f"{key}_saved_log_levels", levels)
    selected_levels = left.multiselect("Visible log severity", levels, default=[level for level in remembered_levels if level in levels], key=f"{key}_log_levels")
    st.session_state[f"{key}_saved_log_levels"] = selected_levels
    query_value = right.text_input("Search recorded notes", value=st.session_state.get(f"{key}_saved_log_search", ""), placeholder="Find a word or source", key=f"{key}_log_search")
    st.session_state[f"{key}_saved_log_search"] = query_value
    query = query_value.strip().lower()
    visible_logs = [row for row in logs if str(row.get("level", "INFO")) in selected_levels and window[0] <= float(row.get("timestamp_s", 0)) <= window[1] and (not query or query in f"{row.get('message', '')} {row.get('source', '')}".lower())]
    st.caption(f"{len(visible_logs)} matching notes · {len(logs)} total")
    if not visible_logs:
        st.info("No notes match these filters. Try another severity, word or time range.")
        return
    with st.expander("Notes on the timeline"):
        fig = go.Figure(go.Scatter(x=[row["timestamp_s"] for row in visible_logs], y=[row.get("level", "INFO") for row in visible_logs], text=[escape(str(row.get("message", "")))[:500] for row in visible_logs], mode="markers", marker=dict(size=7, color=[SEVERITY_COLORS.get(str(row.get("level", "INFO")).upper(), "#627585") for row in visible_logs]), hovertemplate=f"{time_label}: %{{x:.6g}}<br>Severity: %{{y}}<br>%{{text}}<extra></extra>"))
        apply_chart_theme(fig, height=280)
        fig.update_layout(title="Recorded notes", xaxis_title=time_label, yaxis_title="Recorded severity (category)", showlegend=False)
        st.plotly_chart(fig, width="stretch", key=f"{key}_log_chart", config=chart_config(f"{event_id}_logs"))
    show_all = st.checkbox("Show more notes", key=f"{key}_all_logs") if len(visible_logs) > 6 else False
    for row in visible_logs[:50 if show_all else 6]:
        with st.container(border=True):
            coordinate = f"{float(row.get('timestamp_s', 0)):.6g}" + (" · row order" if row_order else " s")
            st.caption(f"{row.get('level', 'INFO')} · {coordinate}" + (f" · {row['source']}" if row.get("source") else ""))
            st.text(str(row.get("message", "")))
    with st.expander("All matching note rows"):
        log_table = pd.DataFrame(visible_logs).reindex(columns=["timestamp_s", "level", "message", "source"]).rename(columns={"timestamp_s": "Row order" if row_order else "Elapsed time (s)", "level": "Severity", "message": "Recorded text", "source": "Source"})
        st.dataframe(log_table, width="stretch", hide_index=True)


