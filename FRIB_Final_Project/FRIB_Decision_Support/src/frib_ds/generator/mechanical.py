from __future__ import annotations
import uuid
from typing import Any
import numpy as np
from frib_ds.generator.base import EventGenerator
from frib_ds.models import EngineeringEvent, Signal, StateEvent, LogEntry, Provenance
from frib_ds.config import get_config

class MechanicalVibrationGenerator(EventGenerator):
    name="mechanical_vibration"; version="1.0"
    def generate(self, seed:int=42, overrides: dict[str, Any] | None = None)->EngineeringEvent:
        c=self.scenario(get_config().scenario(self.name), overrides); rng=np.random.default_rng(seed)
        fs=float(c["sample_rate_hz"]); duration=float(c["duration_s"]); fault=float(c["anomaly_time_s"])
        if fs <= 0 or duration <= 0: raise ValueError("Sample rate and duration must be greater than zero")
        if not 0 < fault < duration: raise ValueError("Anomaly time must be inside the dataset duration")
        t=np.arange(0,duration,1/fs); noise=float(c["noise_std"])
        vib=0.25*np.sin(2*np.pi*float(c["base_frequency_hz"])*t)+rng.normal(0,noise,len(t))
        mask=t>=fault
        vib[mask]+=float(c["fault_amplitude"])*np.sin(2*np.pi*float(c["fault_frequency_hz"])*t[mask])
        temp=24+0.02*t+rng.normal(0,0.03,len(t)); temp[mask]+=0.4*(1-np.exp(-(t[mask]-fault)/2))
        eid=f"MECH-{uuid.uuid4().hex[:8].upper()}"
        sig=lambda n,u,v: Signal(name=n,unit=u,sample_rate_hz=fs,timestamps_s=t.round(6).tolist(),values=np.asarray(v).round(6).tolist())
        return EngineeringEvent(event_id=eid,domain="mechanical",event_type="vibration_anomaly",metadata={"scenario":self.name,"synthetic_ground_truth":{"anomaly_time_s":fault,"fault_frequency_hz":float(c["fault_frequency_hz"])},"seed":seed},signals=[sig("vibration","g",vib),sig("bearing_temperature","C",temp)],states=[StateEvent(timestamp_s=fault,name="VIBRATION_ALARM",value="ACTIVE")],logs=[LogEntry(timestamp_s=fault,message="Synthetic vibration alarm")],provenance=Provenance(source="synthetic_generator",generator_version=self.version,notes="Synthetic demonstration data; not FRIB operational data"))
