"""Transparent ordering of tentative observation patterns, never fault diagnosis.

Candidates are ordered by supporting-observation count, contradictory-observation
count, then stable template order. Counts are not confidence or probabilities.
Only supplied derived features are used; synthetic labels are never consulted.
"""
from __future__ import annotations

import math
from numbers import Real

from frib_ds.models import AnalysisResult, EngineeringEvent, Hypothesis


def _number(values: dict, key: str) -> float | None:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _unit(values: dict, key: str) -> str:
    value = values.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else "unit unspecified"


def _strings(value) -> list[str]:
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def build_hypotheses(event: EngineeringEvent, analysis: AnalysisResult) -> list[Hypothesis]:
    """Build reproducible, evidence-ranked review candidates from actual features.

    A supporting observation means the stated pattern can be observed in the
    supplied features. It does not identify an equipment cause. Missing values
    are limitations, rather than zero measurements or evidence against a fault.
    """
    features = analysis.features if isinstance(analysis.features, dict) else {}
    candidates: list[tuple[Hypothesis, int, int]] = []
    warnings = _strings(features.get("warnings"))

    def add(description, supporting, contrary=None, limitations=None):
        contrary = list(contrary or [])
        if not supporting and not contrary:
            return
        limits = list(limitations or [])
        limits.extend(f"Analysis limitation: {warning}" for warning in warnings)
        limits.append("Observation-pattern ordering is not statistical confidence, a confirmed cause, or operating guidance.")
        candidate = Hypothesis(
            rank=1, description="Tentative review candidate: " + description,
            support="tentative_evidence_pattern",
            supporting_evidence=list(supporting),
            contradicting_evidence=contrary + limits,
        )
        candidates.append((candidate, len(supporting), len(contrary)))

    domain = str(event.domain).lower()
    if domain == "rf":
        reference = _number(features, "trip_time_s")
        decay = _number(features, "approx_decay_ms")
        support, contrary, limits = [], [], []
        if reference is not None:
            kind = features.get("trip_reference")
            kind = kind if isinstance(kind, str) and kind else "reference method unspecified"
            support.append(f"RF reference time: {reference:.6g} s ({kind}).")
        if decay is not None and decay >= 0:
            support.append(f"Observed cavity-field 1/e threshold crossing: {decay:.6g} ms after the reference.")
        else:
            limits.append("A finite nonnegative cavity-field decay estimate is unavailable; field decline cannot be established from this feature alone.")
        if support:
            limits.append("The field threshold and event timing do not determine which condition initiated the event.")
            add("a cavity-field decline may be temporally associated with the RF reference.", support, contrary, limits)

        pre = _number(features, "pressure_pre_mean")
        post = _number(features, "pressure_post_mean")
        delta = _number(features, "pressure_delta")
        support, contrary, limits = [], [], []
        unit = _unit(features, "pressure_unit")
        if pre is not None and post is not None:
            comparison = f"Tuner-pressure window means: pre={pre:.6g}, post={post:.6g} {unit}."
            (support if post != pre else contrary).append(comparison)
        elif delta is not None:
            comparison = f"Derived tuner-pressure pre/post change: {delta:.6g} {unit}."
            (support if delta != 0 else contrary).append(comparison)
            limits.append("Separate pre/post pressure means are unavailable.")
        if pre is not None and post is not None and delta is not None:
            # Do not count a delta derived from the same means as new evidence.
            limits.append(f"Reported pressure delta: {delta:.6g} {unit}; this is not independent of the window means.")
        if support or contrary:
            if reference is not None:
                support.append(f"Pressure windows are associated with RF reference time {reference:.6g} s.")
            limits.append("Window averages do not establish precursor ordering or a pressure-related root cause.")
            add("tuner-pressure variation may accompany the RF event.", support, contrary, limits)

        comparison = features.get("forward_reflected_comparison")
        comparison = comparison if isinstance(comparison, dict) else {}
        peak = _number(features, "peak_reflected_power")
        baseline = _number(comparison, "pre_reflected_mean")
        forward = _number(comparison, "pre_forward_mean")
        support, contrary, limits = [], [], []
        unit = _unit(features, "power_unit")
        if peak is not None and baseline is not None:
            observation = f"Reflected-power event-window peak={peak:.6g}, pre-window mean={baseline:.6g} {unit}."
            (support if peak > baseline else contrary).append(observation)
        elif peak is not None:
            support.append(f"Reflected-power event-window peak: {peak:.6g} {unit}.")
            limits.append("A pre-window reflected-power baseline is unavailable; a change cannot be established.")
        if forward is not None:
            support.append(f"Pre-window forward-power mean: {forward:.6g} {_unit(comparison, 'forward_unit')}.")
        if support or contrary:
            limits.append("Peak-versus-mean comparison has no calibrated anomaly threshold and cannot identify a fault source.")
            add("the reflected/forward-power pattern may merit comparison with the event timeline.", support, contrary, limits)

        emission = features.get("field_emission", features)
        emission = emission if isinstance(emission, dict) else {}
        xray = _number(emission, "xray_peak")
        low = _number(emission, "gradient_min")
        high = _number(emission, "gradient_max")
        correlation = _number(emission, "xray_gradient_correlation")
        support, contrary = [], []
        if xray is not None:
            support.append(f"Captured X-ray peak: {xray:.6g} {_unit(emission, 'xray_unit')}.")
        if low is not None and high is not None:
            observation = f"Captured gradient range: {low:.6g} to {high:.6g} {_unit(emission, 'gradient_unit')}."
            (support if high > low else contrary).append(observation)
        if correlation is not None and -1 <= correlation <= 1:
            observation = f"Descriptive X-ray/gradient correlation: {correlation:.6g}."
            (support if correlation != 0 else contrary).append(observation)
        if support or contrary:
            add("the recorded X-ray/gradient pattern may merit review.", support, contrary,
                ["Descriptive peaks, ranges and correlation do not diagnose field emission, conditioning effectiveness, or a safe gradient."])

    elif domain == "mechanical":
        pre, post = _number(features, "rms_pre"), _number(features, "rms_post")
        reference = _number(features, "anomaly_time_s")
        if pre is not None and post is not None and pre >= 0 and post >= 0:
            observation = f"Vibration RMS: pre={pre:.6g}, post={post:.6g} {_unit(features, 'rms_unit')}."
            support, contrary = ([observation], []) if post > pre else ([], [observation + " Post-reference RMS did not increase."])
            if reference is not None:
                support.append(f"Vibration reference time: {reference:.6g} s.")
            add("increased vibration amplitude may accompany the event.", support, contrary,
                ["An RMS increase does not identify imbalance, bearing damage, or another mechanical cause."])
        frequency, amplitude = _number(features, "dominant_frequency_hz"), _number(features, "fft_peak")
        if frequency is not None and frequency > 0:
            support = [f"Derived post-reference FFT maximum: {frequency:.6g} Hz."]
            if amplitude is not None and amplitude >= 0:
                support.append(f"FFT-maximum amplitude: {amplitude:.6g} {_unit(features, 'fft_amplitude_unit')}.")
            add("frequency-specific vibration behavior may merit review.", support, [],
                ["An FFT maximum exists even for noise; spectral significance and the physical source are unvalidated."])

    elif domain == "plc":
        sequence = _strings(features.get("sequence"))
        interlock = _number(features, "interlock_time_s")
        expected = features.get("expected_sequence_observed")
        if sequence or interlock is not None:
            support, contrary = [], []
            if sequence:
                observation = "Recorded chronological PLC sequence: " + " -> ".join(sequence) + "."
                if "WARNING" in sequence and "INTERLOCKED" in sequence and sequence.index("WARNING") < sequence.index("INTERLOCKED"):
                    support.append(observation)
                else:
                    contrary.append(observation + " A warning-before-interlock progression is not present in this capture.")
            if interlock is not None:
                support.append(f"First recorded PLC interlock: {interlock:.6g} s.")
            if expected is True:
                support.append("The configured expected state sequence was observed in order.")
            elif expected is False:
                contrary.append("The configured expected state sequence was not observed in order.")
            add("a recorded warning/interlock progression may characterize the event.", support, contrary,
                ["Recorded state chronology does not establish why an interlock occurred."])
        if expected is False:
            add("incomplete capture or unexpected state ordering may affect the reconstruction.",
                ["The configured expected state sequence was not observed in order."], [],
                ["Missing or out-of-order states do not by themselves identify a PLC or equipment fault."])
        elif expected is True:
            add("incomplete capture or unexpected state ordering may affect the reconstruction.", [],
                ["The configured expected sequence was observed in order, weakening this explanation."],
                ["A matching sequence does not establish that all relevant signals and logs were captured."])

    if not candidates:
        return [Hypothesis(
            rank=1,
            description="Tentative review candidate: available finite features are insufficient to distinguish an engineering explanation.",
            support="tentative_evidence_pattern",
            supporting_evidence=_strings(analysis.findings),
            contradicting_evidence=["No supported domain-specific observation pattern could be formed. Missing estimates are not evidence of a normal or faulty condition."] + [f"Analysis limitation: {warning}" for warning in warnings],
        )]
    ordered = sorted(candidates, key=lambda item: (-item[1], item[2]))
    return [candidate.model_copy(update={"rank": rank}) for rank, (candidate, _, _) in enumerate(ordered, 1)]
