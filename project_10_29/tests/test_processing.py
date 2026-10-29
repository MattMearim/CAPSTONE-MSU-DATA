from frib_ds.generator.registry import GeneratorRegistry
from frib_ds.processing.registry import ProcessorRegistry

def test_rf_ground_truth_timing():
    e=GeneratorRegistry().for_domain("rf").generate(42); a=ProcessorRegistry().get("rf").process(e)
    assert abs(a.features["trip_time_s"]-e.metadata["synthetic_ground_truth"]["trip_time_s"])<1e-9
    assert a.features["pressure_delta"]>0

def test_mechanical_fault_frequency():
    e=GeneratorRegistry().for_domain("mechanical").generate(42); a=ProcessorRegistry().get("mechanical").process(e)
    target=e.metadata["synthetic_ground_truth"]["fault_frequency_hz"]
    assert abs(a.features["dominant_frequency_hz"]-target)<2.0
    assert a.features["rms_post"]>a.features["rms_pre"]

def test_plc_sequence():
    e=GeneratorRegistry().for_domain("plc").generate(42); a=ProcessorRegistry().get("plc").process(e)
    assert a.features["sequence"][:3]==["RUNNING","WARNING","INTERLOCKED"]
