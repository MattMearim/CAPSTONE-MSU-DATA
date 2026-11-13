from __future__ import annotations
import uuid
from typing import Any
import numpy as np
from frib_ds.generator.base import EventGenerator
from frib_ds.models import EngineeringEvent, Signal, StateEvent, LogEntry, Provenance
from frib_ds.config import get_config

class PLCInterlockGenerator(EventGenerator):
    name="plc_interlock"; version="1.0"
    def generate(self, seed:int=42, overrides: dict[str, Any] | None = None)->EngineeringEvent:
        c=self.scenario(get_config().scenario(self.name), overrides); rng=np.random.default_rng(seed)
        fs=float(c["sample_rate_hz"]); duration=float(c["duration_s"])
        warning=float(c["warning_time_s"]); inter=float(c["interlock_time_s"]); reset=float(c["reset_time_s"])
        if fs <= 0 or duration <= 0: raise ValueError("Sample rate and duration must be greater than zero")
        if not (0 < warning < inter < reset < duration): raise ValueError("Times must satisfy warning < interlock < reset < duration")
        t=np.arange(0,duration,1/fs)
        sensor=0.35+rng.normal(0,0.01,len(t)); m=t>=warning; sensor[m]+=0.9*np.clip((t[m]-warning)/(inter-warning),0,1)
        eid=f"PLC-{uuid.uuid4().hex[:8].upper()}"
        states=[StateEvent(timestamp_s=0,name="PLC_STATE",value="RUNNING"),StateEvent(timestamp_s=warning,name="PLC_STATE",value="WARNING"),StateEvent(timestamp_s=inter,name="PLC_STATE",value="INTERLOCKED"),StateEvent(timestamp_s=reset,name="PLC_STATE",value="RESET_PENDING")]
        signal=Signal(name="process_sensor",unit="normalized",sample_rate_hz=fs,timestamps_s=t.round(6).tolist(),values=sensor.round(6).tolist())
        return EngineeringEvent(event_id=eid,domain="plc",event_type="interlock_sequence",metadata={"scenario":self.name,"synthetic_ground_truth":{"warning_time_s":warning,"interlock_time_s":inter,"reset_time_s":reset},"seed":seed},signals=[signal],states=states,logs=[LogEntry(timestamp_s=warning,message="Warning threshold reached"),LogEntry(timestamp_s=inter,message="PLC interlock latched")],provenance=Provenance(source="synthetic_generator",generator_version=self.version,notes="Synthetic demonstration data; not FRIB operational data"))
