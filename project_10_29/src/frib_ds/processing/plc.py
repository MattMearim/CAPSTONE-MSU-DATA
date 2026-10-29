from frib_ds.config import get_config
from frib_ds.processing.base import Processor
from frib_ds.processing.common import align_signals, aligned_plot, event_timeline
from frib_ds.models import EngineeringEvent, AnalysisResult


class PLCProcessor(Processor):
    name = "plc_sequence"
    version = "2.0"
    domain = "plc"

    def process(self, event: EngineeringEvent) -> AnalysisResult:
        states = sorted((state for state in event.states if state.name == "PLC_STATE"), key=lambda state: state.timestamp_s)
        if not states:
            raise ValueError("PLC analysis requires discrete states named 'PLC_STATE'. Import a JSON event containing the state log, or map a CSV state column to PLC_STATE.")
        sequence = [state.value for state in states]
        transition_intervals = []
        intervals = {}
        for index, (previous, following) in enumerate(zip(states, states[1:])):
            duration = float(following.timestamp_s - previous.timestamp_s)
            transition_intervals.append({"from": previous.value, "to": following.value, "start_s": previous.timestamp_s, "end_s": following.timestamp_s, "duration_s": duration})
            key = f"{previous.value}_to_{following.value}_s"
            intervals[key if key not in intervals else f"{key}_{index + 1}"] = duration
        interlock = next((state.timestamp_s for state in states if state.value == "INTERLOCKED"), None)
        required = get_config().processing.get("plc", {}).get("required_sequence", ["RUNNING", "WARNING", "INTERLOCKED"])
        cursor = 0
        for value in sequence:
            if cursor < len(required) and value == required[cursor]:
                cursor += 1
        sequence_matches = cursor == len(required)
        warnings = []
        if not sequence_matches:
            warnings.append("The captured PLC log does not contain the configured expected sequence in order; capture coverage or state mapping may be incomplete.")
        findings = ["Observed chronological PLC sequence: " + " -> ".join(sequence)]
        if interlock is not None:
            findings.append(f"First recorded PLC interlock: {interlock:.6g} s.")
        plots = [{"kind": "state_timeline", "state_name": "PLC_STATE", "timestamps_s": [state.timestamp_s for state in states], "states": sequence, "title": "Recorded PLC states"}]
        alignment = None
        if event.signals:
            t, values, alignment = align_signals(event.signals)
            warnings.extend(alignment["warnings"])
            plots.append(aligned_plot(t, values, event.signals, "Aligned PLC signals", interlock))
        return AnalysisResult(
            event_id=event.event_id, processor=self.name, processor_version=self.version,
            features={"sequence": sequence, "intervals": intervals, "transition_intervals": transition_intervals, "interlock_time_s": interlock, "expected_sequence": required, "expected_sequence_observed": sequence_matches, "processing": {"alignment": alignment}, "warnings": warnings},
            timeline=event_timeline(event), findings=findings, plot_specs=plots,
        )

