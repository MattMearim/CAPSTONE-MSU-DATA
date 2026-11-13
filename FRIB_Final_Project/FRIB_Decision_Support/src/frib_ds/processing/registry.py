from frib_ds.processing.base import Processor
from frib_ds.processing.rf import RFProcessor
from frib_ds.processing.mechanical import MechanicalProcessor
from frib_ds.processing.plc import PLCProcessor
from frib_ds.processing.evidence import EvidenceProcessor, evidence_summary, summary_findings
import json
import numpy as np
class ProcessorRegistry:
    def __init__(self):
        self._processors={p.domain:p for p in (RFProcessor(),MechanicalProcessor(),PLCProcessor(),EvidenceProcessor())}
    def register(self,p:Processor): self._processors[p.domain]=p
    def get(self,domain:str)->Processor:
        if domain not in self._processors: raise KeyError(f"No processor registered for domain '{domain}'")
        return self._processors[domain]
    def domains(self): return sorted(self._processors)

    def analyze(self,event,expectations=None):
        from frib_ds.quality import assess_event
        quality=assess_event(event,expectations if expectations is not None else event.metadata.get("quality_expectations"))
        timing_issues={"RECORDING_GAP","POTENTIAL_RECORDING_GAP","IRREGULAR_CADENCE","INVALID_TIMESTAMPS","NONFINITE_VALUES"}
        unsafe_timing=any(issue["code"] in timing_issues for issue in quality["issues"])
        names={signal.name for signal in event.signals}
        ready={
            "rf": {"cavity_field","reflected_power","tuner_pressure"}.issubset(names) or (bool(names & {"xray","x_ray","xray_rate","x_ray_rate"}) and bool(names & {"gradient","cavity_gradient"})),
            "mechanical": "vibration" in names,
            "plc": any(state.name=="PLC_STATE" for state in event.states),
        }
        ordinal_time=event.metadata.get("import_summary",{}).get("time_basis")=="row_index"
        if event.domain not in ready or not ready[event.domain] or ordinal_time or unsafe_timing:
            result=EvidenceProcessor().process(event)
            result.features["data_quality"]=quality
            if unsafe_timing:
                result.features["warnings"].append("Data-quality checks found missing or irregular timing. Domain alignment, duration estimates and spectra are withheld to avoid interpolating across unrecorded intervals; review the quality report and source capture.")
            if ordinal_time:
                result.features["warnings"].append("Only record order is known. Supply timestamps before calculating rates, durations or frequency spectra.")
            elif event.domain in ready and not ready[event.domain]:
                result.features["warnings"].append(f"The required {event.domain} engineering channels were not provided. A descriptive evidence summary is available; map the expected channels to enable domain analysis.")
            return result
        try:
            with np.errstate(over="raise",invalid="raise",divide="raise"):
                result=self.get(event.domain).process(event)
        except (FloatingPointError,OverflowError):
            return self._range_fallback(event,quality)
        try:
            json.dumps(result.model_dump(mode="json"),allow_nan=False)
        except ValueError:
            return self._range_fallback(event,quality)
        result.features["data_quality"]=quality
        summary=evidence_summary(event)
        result.features["evidence_summary"]=summary
        result.findings.extend(summary_findings(summary))
        result.features.setdefault("warnings",[]).extend(event.metadata.get("unit_normalization",{}).get("warnings",[]))
        return result

    @staticmethod
    def _range_fallback(event,quality):
        from frib_ds.quality.common import make_issue,make_report
        issue=make_issue("NUMERICAL_RANGE","warning","Domain calculation exceeded a reliable numeric range",
            "Finite source values produced an overflow or nonfinite domain result. The application retained the evidence and withheld those calculations.",
            suggestion="Confirm source units, sensor ranges and numeric values before rerunning domain analysis; descriptive values remain available.")
        report=make_report("L2",[*quality["issues"],issue])
        report.update(expectations=quality["expectations"],location_basis=quality["location_basis"])
        result=EvidenceProcessor().process(event)
        result.features["data_quality"]=report
        result.features["warnings"].append(issue["message"])
        return result
