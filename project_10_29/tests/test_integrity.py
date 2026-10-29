import pytest
from pydantic import ValidationError

from frib_ds.models import Signal, EngineeringEvent, ReviewRequest
from frib_ds.generator.registry import GeneratorRegistry


def signal(**overrides):
    return Signal(**{**dict(name="sensor", sample_rate_hz=1, timestamps_s=[0, 1], values=[1, 2]), **overrides})


@pytest.mark.parametrize("overrides", [dict(sample_rate_hz=0), dict(values=[1]), dict(values=[1, float("nan")]), dict(timestamps_s=[1, 1]), dict(timestamps_s=[1, 0]), dict(timestamps_s=[0, float("inf")])])
def test_invalid_samples_rejected(overrides):
    with pytest.raises(ValidationError):
        signal(**overrides)


@pytest.mark.parametrize("event_id", ["../outside", "C:\\file", "A/B", "CON", "..", ""])
def test_unsafe_event_id_rejected(event_id):
    with pytest.raises(ValidationError):
        EngineeringEvent(event_id=event_id, domain="rf", event_type="test", provenance={"source": "test"})


def test_duplicate_signals_rejected():
    with pytest.raises(ValidationError):
        EngineeringEvent(event_id="E1", domain="rf", event_type="test", provenance={"source": "test"}, signals=[signal(), signal()])


@pytest.mark.parametrize("overrides", [dict(sample_rate_hz=100000000), dict(field_decay_tau_s=0), dict(noise_std=-1), dict(unknown=1), dict(pressure_rise_start_s="nan"), dict(reflected_power_rise_start_s="inf")])
def test_generator_rejects_unbounded_or_invalid_parameters(overrides):
    with pytest.raises(ValueError):
        GeneratorRegistry().for_domain("rf").generate(42, overrides)


def test_review_requires_named_person_and_valid_correction():
    with pytest.raises(ValidationError):
        ReviewRequest(decision="approve")
    with pytest.raises(ValidationError):
        ReviewRequest(decision="approve", reviewer="   ")
    with pytest.raises(ValidationError):
        ReviewRequest(decision="correct", reviewer="engineer")
