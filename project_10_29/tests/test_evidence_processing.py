import json
import pytest
from frib_ds.models import EngineeringEvent, Signal
from frib_ds.processing.registry import ProcessorRegistry


def captured(**kwargs):
    return EngineeringEvent(event_id="MIXED-TEST", domain="rf", event_type="evidence_record", provenance={"source":"test"}, **kwargs)


def test_text_only_capture_is_described_without_claiming_a_cause():
    event = captured(logs=[{"timestamp_s":0,"message":"No pressure fault observed","level":"INFO"},
                           {"timestamp_s":1,"message":"WARNING: review interlock log","level":"WARNING"}])
    result = ProcessorRegistry().analyze(event)
    assert result.processor == "mixed_evidence_summary"
    summary = result.features["evidence_summary"]
    assert summary["text_records"] == 2 and summary["numeric_channels"] == 0
    assert summary["log_severity_counts"] == {"INFO":1,"WARNING":1}
    assert summary["reported_term_mentions"]["fault"] == 1
    assert "do not establish" in summary["interpretation"]
    assert any("No pressure fault observed" in finding for finding in result.findings)
    assert any("required rf engineering channels" in warning for warning in result.features["warnings"])
    assert result.plot_specs[0]["state_name"] == "Reported log severity"
    assert len(result.timeline) == 2


def test_categorical_events_are_chronological_and_never_numeric_samples():
    event = captured(states=[{"timestamp_s":2,"name":"mode","value":"RUNNING"},
                             {"timestamp_s":0,"name":"mode","value":"IDLE"},
                             {"timestamp_s":1,"name":"mode","value":"IDLE"}])
    result = ProcessorRegistry().analyze(event)
    category = result.features["evidence_summary"]["categories"]["mode"]
    assert category["first_value"] == "IDLE" and category["last_value"] == "RUNNING"
    assert category["observed_changes"] == 1
    assert category["recorded_events"] == 3
    assert result.plot_specs[0]["states"] == ["IDLE","IDLE","RUNNING"]
    assert result.features["measurement_summary"] == {}


def test_unrelated_measurements_keep_native_times_and_explicit_units():
    event = captured(signals=[Signal(name="vacuum",unit="Pa",sample_rate_hz=1,timestamps_s=[0,1],values=[10,20]),
                              Signal(name="temperature",unit="K",sample_rate_hz=1,timestamps_s=[8,9],values=[290,300])])
    before = event.model_dump(mode="json")
    result = ProcessorRegistry().analyze(event)
    assert result.plot_specs[0]["timestamps_s"] == [0,1]
    assert result.plot_specs[1]["timestamps_s"] == [8,9]
    assert result.features["measurement_summary"]["vacuum"]["mean"] == 15
    assert result.plot_specs[1]["units"] == {"temperature":"K"}
    assert event.model_dump(mode="json") == before


def test_summary_mean_stays_finite_for_large_finite_values():
    event = captured(signals=[Signal(name="large",unit="1",sample_rate_hz=1,timestamps_s=[0,1],values=[1e308,1e308])])
    result = ProcessorRegistry().analyze(event)
    assert result.features["measurement_summary"]["large"]["mean"] == pytest.approx(1e308)
    json.dumps(result.model_dump(mode="json"),allow_nan=False)


def test_unknown_timing_never_produces_spectral_or_duration_estimates():
    event = captured(metadata={"import_summary":{"time_basis":"row_index","notes":["No measured timing supplied."]}},
                     signals=[Signal(name="vibration",unit="m/s^2",sample_rate_hz=1,timestamps_s=[0,1,2,3],values=[0,1,0,-1])])
    event.domain = "mechanical"
    result = ProcessorRegistry().analyze(event)
    assert result.processor == "mixed_evidence_summary"
    assert "dominant_frequency_hz" not in result.features
    assert all(plot.get("kind") != "fft" for plot in result.plot_specs)
    assert result.plot_specs[0]["time_label"] == "Record order (not elapsed time)"
    assert "No measured timing supplied." in result.features["warnings"]


def test_booleans_cannot_be_silently_coerced_to_numeric_samples():
    with pytest.raises(ValueError,match="categorical"):
        Signal(name="enabled",unit="1",sample_rate_hz=1,timestamps_s=[0,1],values=[True,False])
