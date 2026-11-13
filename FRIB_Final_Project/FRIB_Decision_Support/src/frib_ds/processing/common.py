"""Deterministic analysis helpers that leave raw evidence unchanged."""
from __future__ import annotations

import numpy as np
from scipy.signal import get_window
from frib_ds.models import Signal, TimelineItem


def arrays(signal: Signal):
    return np.asarray(signal.timestamps_s, dtype=float), np.asarray(signal.values, dtype=float)


def find_signal(event, name):
    for signal in event.signals:
        if signal.name == name:
            return signal
    available = ", ".join(signal.name for signal in event.signals) or "none"
    raise ValueError(f"Analysis requires signal '{name}'. Available signals: {available}. Map the imported column to '{name}' or choose the matching domain.")


def clean_signal(signal: Signal):
    """Return finite, sorted, deduplicated copies and record transformations.

    Validated contracts already enforce these properties. This also supports
    adapters supplying an unvalidated Signal. Equal-time samples are averaged.
    """
    t, values = arrays(signal)
    if len(t) != len(values):
        raise ValueError(f"Signal '{signal.name}' has different timestamp and value counts.")
    original_count = len(t)
    finite = np.isfinite(t) & np.isfinite(values)
    removed = int((~finite).sum())
    t, values = t[finite], values[finite]
    order = np.argsort(t, kind="stable")
    reordered = not np.array_equal(order, np.arange(len(t)))
    t, values = t[order], values[order]
    unique, inverse, counts = np.unique(t, return_inverse=True, return_counts=True)
    duplicates = int(len(t) - len(unique))
    if duplicates:
        values = np.bincount(inverse, weights=values) / counts
        t = unique
    if len(t) < 2:
        raise ValueError(f"Signal '{signal.name}' needs at least two finite samples at distinct timestamps.")
    median_dt = float(np.median(np.diff(t)))
    measured_rate = 1.0 / median_dt
    irregular = not np.allclose(np.diff(t), median_dt, rtol=0.01, atol=1e-9)
    record = {
        "input_samples": original_count,
        "clean_samples": len(t),
        "removed_nonfinite_samples": removed,
        "reordered": reordered,
        "duplicate_timestamps_averaged": duplicates,
        "declared_sample_rate_hz": float(signal.sample_rate_hz),
        "timestamp_sample_rate_hz": measured_rate,
        "irregular_sampling": irregular,
        "unit": signal.unit or "unspecified",
    }
    return t.copy(), values.copy(), record


def align_signals(signals: list[Signal], sample_rate_hz: float | None = None):
    """Resample onto a uniform grid inside the true common capture interval.

    The fastest timestamp-derived rate preserves fast signals when slower
    auxiliary channels are overlaid. Interpolation adds no measured bandwidth.
    """
    if not signals:
        raise ValueError("Select at least one signal for alignment.")
    cleaned = {signal.name: clean_signal(signal) for signal in signals}
    if len(cleaned) != len(signals):
        raise ValueError("Signal names must be unique for alignment.")
    start = max(row[0][0] for row in cleaned.values())
    end = min(row[0][-1] for row in cleaned.values())
    rate = float(sample_rate_hz) if sample_rate_hz is not None else max(row[2]["timestamp_sample_rate_hz"] for row in cleaned.values())
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("Alignment sample rate must be finite and positive.")
    count = int(np.floor((end - start) * rate + 1e-8)) + 1
    if end <= start or count < 2:
        raise ValueError("Signals need at least two samples in a shared time interval; capture windows do not overlap sufficiently.")
    if count > 1_000_000:
        raise ValueError("Aligned output exceeds 1,000,000 samples. Import a shorter capture or a lower sample rate.")
    grid = float(start) + np.arange(count, dtype=float) / rate
    grid = grid[grid <= float(end) + 1e-10]
    values = {name: np.interp(grid, row[0], row[1]) for name, row in cleaned.items()}
    warnings = []
    for name, (_, _, record) in cleaned.items():
        native_rate = record["timestamp_sample_rate_hz"]
        if record["irregular_sampling"]:
            warnings.append(f"{name}: irregular timestamps were linearly resampled; large gaps can limit spectral interpretation.")
        if not np.isclose(native_rate, record["declared_sample_rate_hz"], rtol=0.02):
            warnings.append(f"{name}: declared sample rate differs from timestamps; analysis uses timestamps.")
        if rate > native_rate * 1.02:
            warnings.append(f"{name}: interpolated onto a faster overlay grid; interpolation does not add measured bandwidth.")
        if rate < native_rate * 0.98:
            warnings.append(f"{name}: requested downsampling has no anti-alias filter; do not use this overlay for spectral conclusions.")
    metadata = {
        "overlap_start_s": float(grid[0]), "overlap_end_s": float(grid[-1]),
        "output_samples": len(grid), "sample_rate_hz": rate,
        "interpolation": "linear; no extrapolation", "raw_evidence_unchanged": True,
        "signals": {name: row[2] for name, row in cleaned.items()}, "warnings": warnings,
    }
    return grid, values, metadata


def nearest_index(t: np.ndarray, x: float) -> int:
    if not len(t):
        raise ValueError("Cannot locate an event in an empty signal.")
    return int(np.argmin(np.abs(t - x)))


def fft_spectrum(values, fs: float, window="hann"):
    """Single-sided amplitude spectrum with coherent-window-gain correction."""
    values = np.asarray(values, dtype=float)
    if len(values) < 4 or not np.isfinite(values).all() or not np.isfinite(fs) or fs <= 0:
        raise ValueError("FFT requires at least four finite, uniformly spaced samples and a positive sample rate.")
    centered = values - np.mean(values)
    weights = get_window(window, len(values))
    gain = float(weights.sum())
    if gain <= 0:
        raise ValueError("FFT window has zero gain.")
    amplitude = np.abs(np.fft.rfft(centered * weights)) / gain
    if len(values) % 2 == 0:
        amplitude[1:-1] *= 2
    else:
        amplitude[1:] *= 2
    return np.fft.rfftfreq(len(values), 1 / fs), amplitude


def dominant_frequency(values, fs, window="hann"):
    if len(values) < 4:
        return 0.0, 0.0
    frequencies, amplitude = fft_spectrum(values, fs, window)
    peak = 1 + int(np.argmax(amplitude[1:]))
    return float(frequencies[peak]), float(amplitude[peak])


def spectrum_for_signal(signal: Signal, start: float, end: float, warnings: list[str], window="hann"):
    """FFT on the primary signal's own timestamp-derived uniform grid."""
    native_t, native_values, native = clean_signal(signal)
    start = max(float(start), float(native_t[0]))
    end = min(float(end), float(native_t[-1]))
    rate = native["timestamp_sample_rate_hz"]
    count = int(np.floor((end - start) * rate + 1e-8)) + 1
    if count < 4:
        warnings.append(f"{signal.name}: fewer than four samples in the requested FFT window; no spectrum was estimated.")
        return None, None, None, None
    if count > 1_000_000:
        raise ValueError("FFT output exceeds 1,000,000 samples. Import a shorter capture or a lower sample rate.")
    grid = start + np.arange(count) / rate
    grid = grid[grid <= end + 1e-10]
    uniform_values = np.interp(grid, native_t, native_values)
    frequencies, amplitude = fft_spectrum(uniform_values, rate, window)
    peak = 1 + int(np.argmax(amplitude[1:]))
    metadata = {
        "signal": signal.name, "window": window, "mean_removed": True,
        "amplitude_scaling": "single-sided; coherent window gain corrected",
        "amplitude_unit": signal.unit or "unspecified", "sample_rate_hz": rate,
        "samples": len(grid), "start_s": float(grid[0]), "end_s": float(grid[-1]),
        "frequency_resolution_hz": float(rate / len(grid)),
        "resampling": "linear on native timestamp-derived rate",
    }
    plot = {"kind": "fft", "signal": signal.name, "title": f"{signal.name} amplitude spectrum", "frequencies_hz": frequencies.tolist(), "amplitudes": amplitude.tolist(), "amplitude_unit": metadata["amplitude_unit"]}
    if float(np.ptp(uniform_values)) <= 1e-12:
        warnings.append(f"{signal.name}: constant signal has no resolvable nonzero dominant frequency.")
        return None, None, metadata, plot
    return float(frequencies[peak]), float(amplitude[peak]), metadata, plot


def rms(values):
    values = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(values * values))) if len(values) else None


def window_mean(t, values, start, end, warnings, label, *, include_end=True):
    if start < float(t[0]) - 1e-10 or end > float(t[-1]) + 1e-10:
        warnings.append(f"{label}: the capture covers only part of the requested time window; any estimate uses available samples only.")
    mask = (t >= start) & (t <= end if include_end else t < end)
    if int(mask.sum()) < 2:
        warnings.append(f"{label}: fewer than two captured samples in the requested time window; no estimate was made.")
        return None
    return float(np.mean(values[mask]))


def event_timeline(event):
    items = [TimelineItem(timestamp_s=state.timestamp_s, event=f"{state.name} -> {state.value}", evidence="state log") for state in event.states]
    items.extend(TimelineItem(timestamp_s=log.timestamp_s, event=log.message, evidence=f"event log: {log.source}") for log in event.logs)
    return sorted(items, key=lambda item: item.timestamp_s)


def aligned_plot(t, values, signals, title, event_time_s=None):
    return {"kind": "timeseries", "title": title, "signals": list(values), "timestamps_s": t.tolist(), "values": {name: series.tolist() for name, series in values.items()}, "units": {signal.name: signal.unit or "unspecified" for signal in signals}, "event_time_s": event_time_s}

