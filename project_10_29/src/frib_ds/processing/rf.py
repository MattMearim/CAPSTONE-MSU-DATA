from __future__ import annotations

import numpy as np

from frib_ds.config import get_config
from frib_ds.models import EngineeringEvent, AnalysisResult, TimelineItem
from frib_ds.processing.base import Processor
from frib_ds.processing.common import align_signals, aligned_plot, clean_signal, event_timeline, find_signal, spectrum_for_signal, window_mean


class RFProcessor(Processor):
    name = "rf_trip"
    version = "2.0"
    domain = "rf"

    def process(self, event: EngineeringEvent) -> AnalysisResult:
        by_name = {signal.name: signal for signal in event.signals}
        xray = next((by_name[name] for name in ("xray", "x_ray", "xray_rate", "x_ray_rate") if name in by_name), None)
        gradient = next((by_name[name] for name in ("gradient", "cavity_gradient") if name in by_name), None)
        if xray and gradient and "cavity_field" not in by_name:
            return self._field_emission(event, xray, gradient)

        cavity = find_signal(event, "cavity_field")
        reflected = find_signal(event, "reflected_power")
        pressure = find_signal(event, "tuner_pressure")
        signals = [cavity, reflected, pressure]
        forward = by_name.get("forward_power")
        if forward:
            signals.append(forward)
        t, values, alignment = align_signals(signals)
        warnings = list(alignment["warnings"])
        config = get_config().processing
        rf_config = config.get("rf", {})
        pre_window = float(rf_config.get("pressure_pre_window_s", 0.5))
        post_window = float(rf_config.get("pressure_post_window_s", 0.05))
        if not np.isfinite(pre_window) or not np.isfinite(post_window) or pre_window <= 0 or post_window <= 0:
            raise ValueError("RF pre/post window settings must be finite, positive durations.")

        interlocks = sorted(state.timestamp_s for state in event.states if "INTERLOCK" in state.name.upper() and state.value.upper() in {"ACTIVE", "INTERLOCKED", "TRUE", "1"})
        cavity_t, cavity_values, _ = clean_signal(cavity)
        trip = float(interlocks[0]) if interlocks else float(cavity_t[np.argmin(np.gradient(cavity_values, cavity_t))])
        reference = "state log" if interlocks else "derived cavity-field slope"
        if not interlocks:
            warnings.append("No active interlock timestamp was supplied; reference time is inferred from the steepest cavity-field decline.")
        if trip < t[0] or trip > t[-1]:
            warnings.append("The event reference lies outside the shared signal capture; pre/post estimates may be unavailable.")
        pre_pressure = window_mean(t, values[pressure.name], trip - pre_window, trip, warnings, "Pre-event tuner pressure", include_end=False)
        post_pressure = window_mean(t, values[pressure.name], trip, trip + post_window, warnings, "Post-event tuner pressure")
        pressure_delta = post_pressure - pre_pressure if pre_pressure is not None and post_pressure is not None else None

        near = (t >= trip - post_window) & (t <= trip + post_window)
        peak_reflected = float(np.max(values[reflected.name][near])) if np.any(near) else None
        if peak_reflected is None:
            warnings.append("No reflected-power samples cover the event window.")

        decay_ms = None
        before = np.where(cavity_t < trip)[0]
        after = np.where(cavity_t >= trip)[0]
        if len(before) and len(after) and cavity_values[before[-1]] > 0:
            threshold = float(cavity_values[before[-1]] / np.e)
            crossings = after[cavity_values[after] <= threshold]
            if len(crossings):
                index = int(crossings[0])
                crossing_time = float(cavity_t[index])
                if index > 0 and cavity_values[index - 1] > threshold and cavity_values[index - 1] != cavity_values[index]:
                    fraction = (threshold - cavity_values[index - 1]) / (cavity_values[index] - cavity_values[index - 1])
                    crossing_time = float(cavity_t[index - 1] + fraction * (cavity_t[index] - cavity_t[index - 1]))
                decay_ms = max(0.0, crossing_time - trip) * 1000
            else:
                warnings.append("Cavity field did not cross the pre-event 1/e threshold in the capture; no decay time was estimated.")
        else:
            warnings.append("A positive pre-event cavity field and post-event capture are required to estimate field decay.")

        fft_end = float(cavity_t[before[-1]]) if len(before) else float(cavity_t[0])
        frequency, amplitude, fft_metadata, fft_plot = spectrum_for_signal(cavity, float(cavity_t[0]), fft_end, warnings, config.get("common", {}).get("fft_window", "hann"))
        features = {
            "trip_time_s": trip,
            "trip_reference": reference,
            "pressure_pre_mean": pre_pressure,
            "pressure_post_mean": post_pressure,
            "pressure_delta": pressure_delta,
            "pressure_unit": pressure.unit or "unspecified",
            "pressure_pre_window_s": [trip - pre_window, trip],
            "pressure_post_window_s": [trip, trip + post_window],
            "peak_reflected_power": peak_reflected,
            "power_unit": reflected.unit or "unspecified",
            "approx_decay_ms": decay_ms,
            "decay_method": "First crossing of positive pre-event cavity field / e, interpolated using actual timestamps; not a fitted physical cavity parameter",
            "pretrip_dominant_frequency_hz": frequency,
            "pretrip_fft_peak": amplitude,
            "processing": {"alignment": alignment, "fft": fft_metadata},
        }
        if forward:
            forward_mean = window_mean(t, values[forward.name], trip - pre_window, trip, warnings, "Pre-event forward power", include_end=False)
            reflected_mean = window_mean(t, values[reflected.name], trip - pre_window, trip, warnings, "Pre-event reflected power", include_end=False)
            features["forward_reflected_comparison"] = {
                "pre_forward_mean": forward_mean,
                "pre_reflected_mean": reflected_mean,
                "pre_reflected_to_forward_ratio": reflected_mean / forward_mean if forward_mean is not None and reflected_mean is not None and forward_mean > 0 and forward.unit == reflected.unit else None,
                "forward_unit": forward.unit or "unspecified",
                "reflected_unit": reflected.unit or "unspecified",
                "window_s": [trip - pre_window, trip],
            }
            if forward.unit != reflected.unit:
                warnings.append("Forward/reflected power units differ; a power ratio was not calculated.")
        else:
            warnings.append("No forward_power channel was supplied; forward/reflected comparison is unavailable.")

        findings = [f"Event reference time: {trip:.6g} s ({reference})."]
        if pressure_delta is not None:
            findings.append(f"Tuner-pressure pre/post change: {pressure_delta:.6g} {pressure.unit or '(unit unspecified)'}.")
        if peak_reflected is not None:
            findings.append(f"Peak reflected power in the event window: {peak_reflected:.6g} {reflected.unit or '(unit unspecified)'}.")
        if decay_ms is not None:
            findings.append(f"Approximate cavity-field 1/e threshold crossing: {decay_ms:.4g} ms after the reference time.")
        timeline = event_timeline(event)
        if not interlocks:
            timeline.append(TimelineItem(timestamp_s=trip, event="Inferred cavity-field decline reference", evidence=reference))
        plots = [aligned_plot(t, values, signals, "Aligned RF waveforms", trip)]
        for label, mask in (
            ("Pre-event RF capture", (t >= trip - pre_window) & (t < trip)),
            ("Post-event RF capture", (t >= trip) & (t <= trip + post_window)),
        ):
            if int(mask.sum()) >= 2:
                plots.append(aligned_plot(t[mask], {name: series[mask] for name, series in values.items()}, signals, label, trip))
        if fft_plot:
            plots.append(fft_plot)
        if xray and gradient:
            field_emission = self._field_emission(event, xray, gradient)
            features["field_emission"] = field_emission.features
            findings.extend(field_emission.findings)
            plots.extend(field_emission.plot_specs)
            warnings.extend(field_emission.features.get("warnings", []))
        features["warnings"] = warnings
        return AnalysisResult(event_id=event.event_id, processor=self.name, processor_version=self.version, features=features, timeline=sorted(timeline, key=lambda item: item.timestamp_s), findings=findings, plot_specs=plots)

    def _field_emission(self, event, xray, gradient):
        t, values, alignment = align_signals([xray, gradient])
        x, g = values[xray.name], values[gradient.name]
        warnings = list(alignment["warnings"])
        correlation = float(np.corrcoef(g, x)[0, 1]) if len(t) >= 3 and np.std(g) > 0 and np.std(x) > 0 else None
        warnings.append("X-ray/gradient trends are descriptive only; correlation does not establish field emission, conditioning effectiveness, or a safe operating gradient.")
        features = {
            "xray_peak": float(np.max(x)), "xray_mean": float(np.mean(x)), "xray_unit": xray.unit or "unspecified",
            "gradient_min": float(np.min(g)), "gradient_max": float(np.max(g)), "gradient_unit": gradient.unit or "unspecified",
            "xray_gradient_correlation": correlation,
            "processing": {"alignment": alignment}, "warnings": warnings,
        }
        findings = [f"Captured X-ray peak: {features['xray_peak']:.6g} {features['xray_unit']}; gradient range: {features['gradient_min']:.6g} to {features['gradient_max']:.6g} {features['gradient_unit']}."]
        plots = [
            aligned_plot(t, values, [xray, gradient], "Aligned X-ray and gradient trends"),
            {"kind": "scatter", "title": "X-ray versus cavity gradient", "x": g.tolist(), "y": x.tolist(), "x_label": gradient.name, "y_label": xray.name, "x_unit": features["gradient_unit"], "y_unit": features["xray_unit"]},
        ]
        return AnalysisResult(event_id=event.event_id, processor="rf_field_emission_trends", processor_version=self.version, features=features, timeline=event_timeline(event), findings=findings, plot_specs=plots)

