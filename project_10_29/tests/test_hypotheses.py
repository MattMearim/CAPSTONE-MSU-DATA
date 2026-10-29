import json

import pytest

from frib_ds.knowledge.hypotheses import build_hypotheses
from frib_ds.models import AnalysisResult, EngineeringEvent, Provenance


def build(domain, features, metadata=None):
    event = EngineeringEvent(event_id="TEST-HYPOTHESES", domain=domain, event_type="test", metadata=metadata or {}, provenance=Provenance(source="test_capture"))
    analysis = AnalysisResult(event_id=event.event_id, processor="test", processor_version="1", features=features)
    return build_hypotheses(event, analysis)


@pytest.mark.parametrize("domain,features", [
    ("rf", {"trip_time_s": 1.5, "trip_reference": "state log", "approx_decay_ms": 22, "pressure_pre_mean": 1, "pressure_post_mean": 1.3, "pressure_delta": 0.3, "pressure_unit": "bar", "peak_reflected_power": 8, "power_unit": "W", "forward_reflected_comparison": {"pre_reflected_mean": 1, "pre_forward_mean": 10, "forward_unit": "W"}}),
    ("mechanical", {"rms_pre": 0.2, "rms_post": 0.8, "rms_unit": "mm/s", "anomaly_time_s": 2, "dominant_frequency_hz": 40, "fft_peak": 0.5, "fft_amplitude_unit": "mm/s"}),
    ("plc", {"sequence": ["RUNNING", "WARNING", "INTERLOCKED"], "interlock_time_s": 3, "expected_sequence_observed": True}),
])
def test_three_domains_have_tentative_ordered_alternatives(domain, features):
    hypotheses = build(domain, features)
    assert len(hypotheses) >= 2
    assert [hypothesis.rank for hypothesis in hypotheses] == list(range(1, len(hypotheses) + 1))
    assert all(hypothesis.description.startswith("Tentative review candidate:") for hypothesis in hypotheses)
    assert all(hypothesis.support == "tentative_evidence_pattern" for hypothesis in hypotheses)
    assert all(hypothesis.contradicting_evidence for hypothesis in hypotheses)


def test_mechanical_order_changes_when_rms_observations_contradict_increase():
    features = {"rms_pre": 0.2, "rms_post": 0.8, "anomaly_time_s": 2, "dominant_frequency_hz": 40, "fft_peak": 0.5}
    assert "increased vibration" in build("mechanical", features)[0].description
    features["rms_post"] = 0.1
    hypotheses = build("mechanical", features)
    assert "frequency-specific" in hypotheses[0].description
    amplitude = next(hypothesis for hypothesis in hypotheses if "increased vibration" in hypothesis.description)
    assert any("did not increase" in item for item in amplitude.contradicting_evidence)


def test_rf_order_follows_actual_evidence_availability():
    features = {"trip_time_s": 1.5, "approx_decay_ms": 22, "pressure_pre_mean": 1, "pressure_post_mean": 1.3, "pressure_delta": 0.3}
    assert "cavity-field" in build("rf", features)[0].description
    features["approx_decay_ms"] = None
    assert "tuner-pressure" in build("rf", features)[0].description


def test_plc_missing_sequence_strengthens_capture_alternative():
    hypotheses = build("plc", {"sequence": ["INTERLOCKED"], "expected_sequence_observed": False})
    assert "incomplete capture" in hypotheses[0].description
    chronology = next(hypothesis for hypothesis in hypotheses if "warning/interlock" in hypothesis.description)
    assert any("not present" in item for item in chronology.contradicting_evidence)


@pytest.mark.parametrize("bad_value", [None, "not numeric", "12.5", {}, [], True, float("nan"), float("inf"), 10**1000])
def test_unknown_or_nonfinite_features_do_not_become_measurements(bad_value):
    hypotheses = build("mechanical", {"rms_pre": bad_value, "rms_post": bad_value, "dominant_frequency_hz": bad_value, "fft_peak": bad_value})
    assert len(hypotheses) == 1
    assert "insufficient" in hypotheses[0].description
    assert hypotheses[0].supporting_evidence == []
    json.dumps([hypothesis.model_dump() for hypothesis in hypotheses], allow_nan=False)


def test_no_fabricated_missing_measurements_or_units():
    hypotheses = build("rf", {"pressure_delta": 0.375, "pressure_unit": "bar"})
    text = json.dumps([hypothesis.model_dump() for hypothesis in hypotheses])
    assert "0.375 bar" in text
    assert "Separate pre/post pressure means are unavailable" in text
    assert "Reflected-power event-window peak" not in text
    assert "threshold crossing:" not in text
    assert "MV/m" not in text


def test_short_capture_limitations_are_preserved_without_nan():
    hypotheses = build("rf", {"trip_time_s": 0, "approx_decay_ms": None, "pressure_delta": None, "warnings": ["Fewer than two pre-event samples"]})
    assert any("Fewer than two pre-event samples" in item for hypothesis in hypotheses for item in hypothesis.contradicting_evidence)
    assert any("decay estimate is unavailable" in item for hypothesis in hypotheses for item in hypothesis.contradicting_evidence)
    json.dumps([hypothesis.model_dump() for hypothesis in hypotheses], allow_nan=False)


def test_synthetic_ground_truth_cannot_change_hypotheses():
    features = {"rms_pre": 0.2, "rms_post": 0.8, "anomaly_time_s": 2, "dominant_frequency_hz": 40, "fft_peak": 0.5}
    ordinary = build("mechanical", features)
    labeled = build("mechanical", features, {"synthetic_ground_truth": {"root_cause": "Invented bearing fault", "fault_frequency_hz": 99123}})
    assert [hypothesis.model_dump() for hypothesis in ordinary] == [hypothesis.model_dump() for hypothesis in labeled]


def test_optional_field_emission_pattern_does_not_claim_diagnosis():
    hypotheses = build("rf", {"xray_peak": 12, "xray_unit": "counts/s", "gradient_min": 2, "gradient_max": 5, "gradient_unit": "MV/m", "xray_gradient_correlation": 0.7})
    assert "X-ray/gradient pattern" in hypotheses[0].description
    assert any("do not diagnose" in item for item in hypotheses[0].contradicting_evidence)


def test_unknown_domain_has_explicit_insufficient_evidence_fallback():
    hypotheses = build("other", {"unmapped": 99})
    assert len(hypotheses) == 1
    assert "insufficient" in hypotheses[0].description
