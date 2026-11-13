from __future__ import annotations
import uuid
from typing import Any
import numpy as np
from frib_ds.generator.base import EventGenerator
from frib_ds.models import EngineeringEvent, Signal, StateEvent, LogEntry, Provenance
from frib_ds.config import get_config

class RFCavityTripGenerator(EventGenerator):
    name = "rf_cavity_trip"
    version = "1.0"

    def generate(self, seed: int = 42, overrides: dict[str, Any] | None = None) -> EngineeringEvent:
        c = self.scenario(get_config().scenario(self.name), overrides)
        rng = np.random.default_rng(seed)
        fs = float(c["sample_rate_hz"]); duration = float(c["duration_s"]); trip = float(c["trip_time_s"])
        if fs <= 0 or duration <= 0: raise ValueError("Sample rate and duration must be greater than zero")
        if not 0 < trip < duration: raise ValueError("Trip time must be inside the dataset duration")
        if float(c["pressure_rise_start_s"]) >= trip: raise ValueError("Pressure rise must start before the trip")
        if float(c["reflected_power_rise_start_s"]) > trip: raise ValueError("Reflected-power rise must start at or before the trip")
        t = np.arange(0, duration, 1/fs)
        noise = float(c["noise_std"])

        cavity = 1.0 + rng.normal(0, noise, len(t))
        after = t >= trip
        cavity[after] = np.exp(-(t[after]-trip)/float(c["field_decay_tau_s"])) + rng.normal(0, noise, after.sum())

        forward = 0.9 + 0.02*np.sin(2*np.pi*8*t) + rng.normal(0, noise, len(t))
        forward[after] *= np.exp(-(t[after]-trip)/0.025)

        reflected = 0.08 + rng.normal(0, noise, len(t))
        rr = t >= float(c["reflected_power_rise_start_s"])
        reflected[rr] += 0.7*np.exp(-((t[rr]-trip)/0.035)**2)

        pressure = 1.0 + rng.normal(0, noise/2, len(t))
        pr = t >= float(c["pressure_rise_start_s"])
        rise = float(c["pressure_rise_magnitude"])
        pressure[pr] += rise * np.clip((t[pr]-float(c["pressure_rise_start_s"]))/(trip-float(c["pressure_rise_start_s"])), 0, 1)

        eid=f"RF-{uuid.uuid4().hex[:8].upper()}"
        sig=lambda n,u,v: Signal(name=n, unit=u, sample_rate_hz=fs, timestamps_s=t.round(6).tolist(), values=np.asarray(v).round(6).tolist())
        return EngineeringEvent(
            event_id=eid, domain="rf", event_type="cavity_trip",
            metadata={"scenario": self.name, "synthetic_ground_truth": {"trip_time_s": trip, "causal_order": ["pressure_rise","reflected_power_rise","interlock","field_decay"]}, "seed":seed},
            signals=[sig("cavity_field","normalized",cavity),sig("forward_power","normalized",forward),sig("reflected_power","normalized",reflected),sig("tuner_pressure","normalized",pressure)],
            states=[StateEvent(timestamp_s=trip, name="RF_INTERLOCK", value="ACTIVE"), StateEvent(timestamp_s=trip+0.15,name="BEAM_STATE",value="INHIBITED")],
            logs=[LogEntry(timestamp_s=trip-0.15,message="Synthetic tuner pressure rise begins"), LogEntry(timestamp_s=trip,message="Synthetic RF interlock activated")],
            provenance=Provenance(source="synthetic_generator", generator_version=self.version, notes="Synthetic demonstration data; not FRIB operational data")
        )
