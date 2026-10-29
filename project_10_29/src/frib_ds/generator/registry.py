from frib_ds.generator.base import EventGenerator
from frib_ds.generator.rf import RFCavityTripGenerator
from frib_ds.generator.mechanical import MechanicalVibrationGenerator
from frib_ds.generator.plc import PLCInterlockGenerator
from frib_ds.config import get_config

class GeneratorRegistry:
    DOMAIN_MAP = {"rf":"rf_cavity_trip","mechanical":"mechanical_vibration","plc":"plc_interlock"}
    EVENT_TYPES = {"rf_cavity_trip":"cavity_trip","mechanical_vibration":"vibration_anomaly","plc_interlock":"interlock_sequence"}

    def __init__(self):
        self._generators: dict[str, EventGenerator] = {}
        for g in (RFCavityTripGenerator(), MechanicalVibrationGenerator(), PLCInterlockGenerator()):
            self.register(g)

    def register(self, generator: EventGenerator): self._generators[generator.name]=generator
    def get(self, name:str)->EventGenerator:
        if name not in self._generators: raise KeyError(f"Unknown generator: {name}")
        return self._generators[name]
    def for_domain(self, domain:str)->EventGenerator:
        if domain not in self.DOMAIN_MAP: raise KeyError(f"Unsupported demo domain: {domain}")
        return self.get(self.DOMAIN_MAP[domain])
    def names(self): return sorted(self._generators)
    def describe(self):
        cfg=get_config()
        rows=[]
        for domain,name in self.DOMAIN_MAP.items():
            rows.append({
                "domain":domain,
                "generator":name,
                "event_type":self.EVENT_TYPES[name],
                "version":self.get(name).version,
                "defaults":cfg.scenario(name),
            })
        return rows
