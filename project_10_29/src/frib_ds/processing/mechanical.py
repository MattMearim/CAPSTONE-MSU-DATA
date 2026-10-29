from __future__ import annotations

import numpy as np

from frib_ds.config import get_config
from frib_ds.models import EngineeringEvent, AnalysisResult, TimelineItem
from frib_ds.processing.base import Processor
from frib_ds.processing.common import align_signals, aligned_plot, clean_signal, event_timeline, find_signal, rms, spectrum_for_signal


class MechanicalProcessor(Processor):
    name = "mechanical_vibration"
    version = "2.0"
    domain = "mechanical"

    def process(self, event: EngineeringEvent) -> AnalysisResult:
        vibration = find_signal(event, "vibration")
        signals = [vibration] + [signal for signal in event.signals if signal.name == "bearing_temperature"]
        t, values, alignment = align_signals(signals)
        warnings = list(alignment["warnings"])
        native_t, native_values, _ = clean_signal(vibration)
        alarms = sorted(state.timestamp_s for state in event.states if "VIBRATION" in state.name.upper() and state.value.upper() in {"ACTIVE", "TRUE", "1"})
        at = float(alarms[0]) if alarms else float(native_t[np.argmax(np.abs(native_values))])
        reference = "state log" if alarms else "derived maximum absolute vibration"
        if not alarms:
            warnings.append("No vibration alarm timestamp was supplied; reference time is the maximum absolute measured vibration, not a diagnosed onset.")
        pre = native_values[native_t < at]
        post = native_values[native_t >= at]
        pre_rms = rms(pre) if len(pre) >= 2 else None
        post_rms = rms(post) if len(post) >= 2 else None
        if pre_rms is None:
            warnings.append("Fewer than two pre-event vibration samples; pre-event RMS is unavailable.")
        if post_rms is None:
            warnings.append("Fewer than two post-event vibration samples; post-event RMS is unavailable.")
        window = get_config().processing.get("common", {}).get("fft_window", "hann")
        frequency, amplitude, fft_metadata, fft_plot = spectrum_for_signal(vibration, at, float(native_t[-1]), warnings, window)
        unit = vibration.unit or "unspecified"
        findings = [f"Vibration reference time: {at:.6g} s ({reference})."]
        if pre_rms is not None and post_rms is not None:
            findings.append(f"Vibration RMS changed from {pre_rms:.6g} to {post_rms:.6g} {unit}.")
        if frequency is not None:
            findings.append(f"Dominant post-event vibration frequency: {frequency:.6g} Hz.")
        timeline = event_timeline(event)
        if not alarms:
            timeline.append(TimelineItem(timestamp_s=at, event="Inferred vibration reference", evidence=reference))
        plots = [aligned_plot(t, values, signals, "Aligned mechanical signals", at)]
        if fft_plot:
            plots.append(fft_plot)
        return AnalysisResult(
            event_id=event.event_id, processor=self.name, processor_version=self.version,
            features={"anomaly_time_s": at, "anomaly_reference": reference, "rms_pre": pre_rms, "rms_post": post_rms, "rms_unit": unit, "dominant_frequency_hz": frequency, "fft_peak": amplitude, "fft_amplitude_unit": unit, "processing": {"alignment": alignment, "fft": fft_metadata}, "warnings": warnings},
            timeline=sorted(timeline, key=lambda item: item.timestamp_s), findings=findings, plot_specs=plots,
        )

