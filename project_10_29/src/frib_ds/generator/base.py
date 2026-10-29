from abc import ABC, abstractmethod
from typing import Any
import math
from frib_ds.models import EngineeringEvent

class EventGenerator(ABC):
    name: str
    version: str = "1.0"

    def scenario(self, defaults, overrides):
        overrides = overrides or {}
        unknown = set(overrides) - set(defaults)
        if unknown:
            raise ValueError("Unknown scenario parameters: " + ", ".join(sorted(unknown)))
        config = {**defaults, **overrides}
        for key, default in defaults.items():
            if isinstance(default, (int, float)):
                try:
                    config[key] = float(config[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be a finite number") from None
                if not math.isfinite(config[key]):
                    raise ValueError(f"{key} must be finite")
        rate, duration = float(config["sample_rate_hz"]), float(config["duration_s"])
        if not math.isfinite(rate) or not math.isfinite(duration) or rate <= 0 or duration <= 0:
            raise ValueError("Sample rate and duration must be positive finite numbers")
        if not 4 <= rate * duration <= 250000 or rate > 100000:
            raise ValueError("Choose 4 to 250,000 samples per signal and a sample rate at most 100,000 Hz")
        if float(config.get("noise_std", 0)) < 0:
            raise ValueError("Noise level cannot be negative")
        if "field_decay_tau_s" in config and float(config["field_decay_tau_s"]) <= 0:
            raise ValueError("Field decay constant must be greater than zero")
        for key in ("base_frequency_hz", "fault_frequency_hz"):
            if key in config and not 0 < float(config[key]) < rate / 2:
                raise ValueError(f"{key} must be positive and below half the sample rate")
        return config

    @abstractmethod
    def generate(self, seed: int = 42, overrides: dict[str, Any] | None = None) -> EngineeringEvent:
        """Generate one synthetic event. Optional overrides make scenario parameters editable from the UI."""
        raise NotImplementedError
