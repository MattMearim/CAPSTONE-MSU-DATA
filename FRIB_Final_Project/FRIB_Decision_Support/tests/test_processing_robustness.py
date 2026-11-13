"""Analytical and malformed-input checks independent of synthetic ground truth."""
import json

import numpy as np
import pytest

from frib_ds.models import EngineeringEvent, LogEntry, Provenance, Signal, StateEvent
from frib_ds.processing.common import align_signals, clean_signal, fft_spectrum
from frib_ds.processing.mechanical import MechanicalProcessor
from frib_ds.processing.plc import PLCProcessor
from frib_ds.processing.rf import RFProcessor


def signal(name, timestamps, values, rate=10, unit="V"):
    return Signal(name=name, timestamps_s=list(timestamps), values=list(values), sample_rate_hz=rate, unit=unit)


def event(domain, signals=None, states=None, logs=None):
    return EngineeringEvent(event_id="TEST-ANALYSIS", domain=domain, event_type="test", signals=signals or [], states=states or [], logs=logs or [], provenance=Provenance(source="test_capture"))


def test_alignment_uses_common_interval_and_preserves_evidence():
    a = signal("a", [0, 1, 2, 3], [0, 2, 4, 6], rate=1)
    b = signal("b", [0.5, 1, 1.5, 2, 2.5], [1, 2, 3, 4, 5], rate=2)
    original = [a.model_dump(), b.model_dump()]
    t, values, metadata = align_signals([a, b])
    np.testing.assert_allclose(t, [0.5, 1, 1.5, 2, 2.5])
    np.testing.assert_allclose(values["a"], 2 * t)
    np.testing.assert_allclose(values["b"], 2 * t)
    assert metadata["raw_evidence_unchanged"]
    assert metadata["sample_rate_hz"] == 2
    assert [a.model_dump(), b.model_dump()] == original


def test_cleaning_records_each_transformation_without_editing_source():
    # An adapter can supply an unvalidated contract. Normal ingestion rejects it.
    raw = Signal.model_construct(name="raw", sample_rate_hz=1.0, unit="V", timestamps_s=[2, 1, 1, 0, 3], values=[4, 1, 3, 0, float("nan")], metadata={})
    t, values, metadata = clean_signal(raw)
    np.testing.assert_array_equal(t, [0, 1, 2])
    np.testing.assert_array_equal(values, [0, 2, 4])
    assert metadata["removed_nonfinite_samples"] == 1
    assert metadata["duplicate_timestamps_averaged"] == 1
    assert metadata["reordered"]
    assert raw.timestamps_s == [2, 1, 1, 0, 3]


def test_nonoverlapping_captures_have_actionable_error():
    a = signal("a", [0, 1], [0, 1], rate=1)
    b = signal("b", [2, 3], [2, 3], rate=1)
    with pytest.raises(ValueError, match="do not overlap"):
        align_signals([a, b])


def test_fft_frequency_and_amplitude_match_known_sine():
    t = np.arange(2000) / 1000
    frequencies, amplitudes = fft_spectrum(17 + 2.5 * np.sin(2 * np.pi * 40 * t), 1000)
    peak = 1 + np.argmax(amplitudes[1:])
    assert frequencies[peak] == pytest.approx(40)
    assert amplitudes[peak] == pytest.approx(2.5, abs=1e-10)


def test_mechanical_spectrum_uses_timestamps_and_native_bandwidth():
    t = np.arange(2000) / 1000
    vibration = signal("vibration", t, np.sin(2 * np.pi * 40 * t), rate=100, unit="mm/s")
    auxiliary_t = np.arange(2, 19) / 10
    temperature = signal("bearing_temperature", auxiliary_t, np.full(len(auxiliary_t), 24), rate=10, unit="C")
    captured = event("mechanical", [vibration, temperature], [StateEvent(timestamp_s=0.5, name="VIBRATION_ALARM", value="ACTIVE")])
    result = MechanicalProcessor().process(captured)
    assert result.features["dominant_frequency_hz"] == pytest.approx(40, abs=1)
    assert result.features["processing"]["fft"]["sample_rate_hz"] == pytest.approx(1000)
    assert result.features["rms_unit"] == "mm/s"
    assert result.features["processing"]["alignment"]["overlap_start_s"] == pytest.approx(0.2)
    assert any("declared sample rate differs" in warning for warning in result.features["warnings"])


def test_rf_decay_uses_actual_timestamps_and_first_chronological_interlock():
    t = np.array([0, 0.5, 0.75, 1, 1.05, 1.1, 1.2, 1.4, 1.8])
    field = np.ones(len(t))
    field[t >= 1] = np.exp(-(t[t >= 1] - 1) / 0.1)
    signals = [signal("cavity_field", t, field, rate=1000), signal("reflected_power", t, np.full(len(t), 0.1), rate=1000), signal("tuner_pressure", t, np.ones(len(t)), rate=1000)]
    captured = event("rf", signals, [StateEvent(timestamp_s=1.4, name="LATER_INTERLOCK", value="ACTIVE"), StateEvent(timestamp_s=1, name="FIRST_INTERLOCK", value="ACTIVE")], [LogEntry(timestamp_s=0.7, message="operator observation")])
    result = RFProcessor().process(captured)
    assert result.features["trip_time_s"] == 1
    assert result.features["approx_decay_ms"] == pytest.approx(100, abs=1e-8)
    assert [item.timestamp_s for item in result.timeline] == sorted(item.timestamp_s for item in result.timeline)
    assert all(item.evidence != "synthetic ground truth" for item in result.timeline)


def test_short_prepost_capture_returns_missing_estimates_and_warnings():
    t = [0, 0.1]
    captured = event("rf", [signal("cavity_field", t, [1, 0.8]), signal("reflected_power", t, [0.1, 0.2]), signal("tuner_pressure", t, [1, 2])], [StateEvent(timestamp_s=0, name="RF_INTERLOCK", value="ACTIVE")])
    result = RFProcessor().process(captured)
    assert result.features["pressure_delta"] is None
    assert result.features["approx_decay_ms"] is None
    assert result.features["pretrip_dominant_frequency_hz"] is None
    assert result.features["warnings"]
    json.dumps(result.model_dump(mode="json"), allow_nan=False)


def test_missing_required_signal_explains_column_mapping():
    with pytest.raises(ValueError, match="Map the imported column to 'cavity_field'"):
        RFProcessor().process(event("rf", [signal("unmapped", [0, 1], [0, 1], rate=1)]))


def test_field_emission_trends_are_descriptive_and_use_units():
    t = np.arange(20) / 10
    captured = event("rf", [signal("xray", t, 3 * t, unit="counts/s"), signal("cavity_gradient", t, 2 + t, unit="MV/m")])
    result = RFProcessor().process(captured)
    assert result.processor == "rf_field_emission_trends"
    assert result.features["xray_gradient_correlation"] == pytest.approx(1)
    assert result.features["gradient_unit"] == "MV/m"
    assert any("does not establish" in warning for warning in result.features["warnings"])
    assert any(plot["kind"] == "scatter" for plot in result.plot_specs)


def test_plc_sorts_states_and_retains_repeated_transition_intervals():
    states = [StateEvent(timestamp_s=t, name="PLC_STATE", value=value) for t, value in [(5, "INTERLOCKED"), (1, "WARNING"), (0, "RUNNING"), (3, "RUNNING"), (4, "WARNING"), (2, "INTERLOCKED")]]
    result = PLCProcessor().process(event("plc", states=states))
    assert result.features["sequence"] == ["RUNNING", "WARNING", "INTERLOCKED", "RUNNING", "WARNING", "INTERLOCKED"]
    assert result.features["interlock_time_s"] == 2
    assert len(result.features["transition_intervals"]) == 5
    assert len(result.features["intervals"]) == 5
    assert result.features["expected_sequence_observed"]


def test_plc_incomplete_sequence_is_flagged_without_inventing_states():
    states = [StateEvent(timestamp_s=1, name="PLC_STATE", value="INTERLOCKED")]
    result = PLCProcessor().process(event("plc", states=states))
    assert result.features["sequence"] == ["INTERLOCKED"]
    assert not result.features["expected_sequence_observed"]
    assert result.features["warnings"]


def test_constant_vibration_has_no_invented_dominant_frequency():
    t = np.arange(100) / 100
    result = MechanicalProcessor().process(event("mechanical", [signal("vibration", t, np.full(100, 2), rate=100)], [StateEvent(timestamp_s=0.2, name="VIBRATION_ALARM", value="ACTIVE")]))
    assert result.features["dominant_frequency_hz"] is None
    assert any("constant signal" in warning for warning in result.features["warnings"])
