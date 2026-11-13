"""Descriptive summaries of measurements, recorded categories and narrative evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
import re
import numpy as np

from frib_ds.models import AnalysisResult, EngineeringEvent
from frib_ds.processing.base import Processor
from frib_ds.processing.common import event_timeline


def evidence_summary(event: EngineeringEvent) -> dict:
    channels = defaultdict(list)
    for state in sorted(event.states, key=lambda item: item.timestamp_s):
        channels[state.name].append(state)
    categories = {}
    for name, states in channels.items():
        frequencies = Counter(state.value for state in states)
        categories[name] = {
            "recorded_events": len(states),
            "observed_changes": sum(a.value != b.value for a, b in zip(states, states[1:])),
            "values": [{"label": value, "count": count} for value, count in frequencies.most_common(30)],
            "first_value": states[0].value,
            "last_value": states[-1].value,
        }
    severity = Counter(log.level.upper() for log in event.logs)
    mentions = Counter()
    terms = ("vacuum", "pressure", "interlock", "fault", "trip", "temperature", "vibration", "beam", "reset", "warning", "error")
    for log in event.logs:
        for term in terms:
            mentions[term] += len(re.findall(r"\b" + term + r"\b", log.message, flags=re.IGNORECASE))
    ordered_logs=sorted(event.logs, key=lambda item: item.timestamp_s)
    selected=set(range(min(3,len(ordered_logs))))
    selected.update(index for index,log in enumerate(ordered_logs) if log.level.upper() in {"WARNING", "WARN", "ERROR", "CRITICAL", "FATAL", "ALARM"})
    excerpts=[{"timestamp_s": ordered_logs[index].timestamp_s, "level": ordered_logs[index].level,
               "source": ordered_logs[index].source, "text": ordered_logs[index].message[:500]}
              for index in sorted(selected)[:10]]
    return {
        "numeric_channels": len(event.signals), "numeric_samples": sum(len(signal.values) for signal in event.signals),
        "categorical_channels": len(channels), "recorded_state_events": len(event.states),
        "text_records": len(event.logs), "categories": categories,
        "log_severity_counts": dict(severity), "reported_term_mentions": {term: count for term, count in mentions.items() if count},
        "text_excerpts": excerpts,
        "interpretation": "Counts, category changes and quoted text describe recorded evidence. Severity and term mentions do not establish an equipment condition or cause.",
    }


def summary_findings(summary: dict) -> list[str]:
    findings = [f"Evidence contains {summary['numeric_channels']} measurement channels, {summary['categorical_channels']} categorical channels and {summary['text_records']} text records."]
    for name, channel in list(summary["categories"].items())[:12]:
        findings.append(f"Recorded category '{name}': {channel['first_value']} to {channel['last_value']}; {channel['observed_changes']} observed value changes.")
    if summary["log_severity_counts"]:
        findings.append("Recorded text severity labels: " + ", ".join(f"{level}={count}" for level, count in summary["log_severity_counts"].items()) + ".")
    if summary["reported_term_mentions"]:
        findings.append("Text mentions (not diagnoses): " + ", ".join(f"{term}={count}" for term, count in summary["reported_term_mentions"].items()) + ".")
    for excerpt in summary["text_excerpts"][:3]:
        findings.append(f"Recorded text at {excerpt['timestamp_s']:.6g} s [{excerpt['level']}]: {excerpt['text'][:240]}")
    return findings


class EvidenceProcessor(Processor):
    name = "mixed_evidence_summary"
    version = "1.0"
    domain = "other"

    def process(self, event: EngineeringEvent) -> AnalysisResult:
        summary = evidence_summary(event)
        findings = summary_findings(summary)
        plots = []
        numeric = {}
        for signal in event.signals:
            values = np.asarray(signal.values, dtype=float)
            magnitude = float(np.max(np.abs(values)))
            stable_mean = float(np.mean(values / magnitude) * magnitude) if magnitude else 0.0
            numeric[signal.name] = {"unit": signal.unit or "unspecified", "samples": len(values),
                                    "minimum": float(np.min(values)), "maximum": float(np.max(values)),
                                    "mean": stable_mean, "first": float(values[0]), "last": float(values[-1])}
            plots.append({"kind": "timeseries", "title": f"Recorded {signal.name.replace('_', ' ')}",
                          "timestamps_s": signal.timestamps_s, "values": {signal.name: signal.values},
                          "units": {signal.name: signal.unit or "unspecified"},
                          "labels": {signal.name: signal.metadata.get("display_label", signal.name.replace("_", " "))}})
        by_name = defaultdict(list)
        for state in sorted(event.states, key=lambda item: item.timestamp_s):
            by_name[state.name].append(state)
        for name, states in list(by_name.items())[:20]:
            plots.append({"kind": "state_timeline", "state_name": name, "title": f"Recorded {name.replace('_', ' ')}",
                          "timestamps_s": [state.timestamp_s for state in states], "states": [state.value for state in states]})
        if event.logs:
            logs = sorted(event.logs, key=lambda item: item.timestamp_s)
            plots.append({"kind": "state_timeline", "state_name": "Reported log severity", "title": "Text record chronology",
                          "timestamps_s": [log.timestamp_s for log in logs], "states": [log.level for log in logs],
                          "messages": [log.message[:500] for log in logs]})
        import_summary=event.metadata.get("import_summary", {})
        warnings = list(dict.fromkeys([*import_summary.get("warnings", []),*import_summary.get("notes", [])]))
        warnings.extend(event.metadata.get("unit_normalization", {}).get("warnings", []))
        warnings.append("This is a descriptive evidence summary; no domain-specific physical diagnosis was calculated.")
        time_basis=event.metadata.get("import_summary",{}).get("time_basis","elapsed_seconds")
        for plot in plots:
            plot["time_label"]="Record order (not elapsed time)" if time_basis=="row_index" else "Elapsed time (s)"
        return AnalysisResult(event_id=event.event_id, processor=self.name, processor_version=self.version,
                              features={"evidence_summary": summary, "measurement_summary": numeric, "warnings": warnings,"time_basis":time_basis},
                              timeline=event_timeline(event), findings=findings, plot_specs=plots)
