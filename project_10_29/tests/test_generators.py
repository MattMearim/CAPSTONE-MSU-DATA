from frib_ds.generator.registry import GeneratorRegistry

def test_three_domains_generate():
    r=GeneratorRegistry()
    for domain in ["rf","mechanical","plc"]:
        e=r.for_domain(domain).generate(42)
        assert e.domain==domain
        assert e.provenance.source=="synthetic_generator"
        assert e.signals or e.states

def test_custom_generator_overrides_are_applied():
    r=GeneratorRegistry()
    e=r.get("rf_cavity_trip").generate(7,{"duration_s":2.0,"sample_rate_hz":100.0,"trip_time_s":1.2,"pressure_rise_start_s":1.0,"reflected_power_rise_start_s":1.1})
    assert e.metadata["synthetic_ground_truth"]["trip_time_s"]==1.2
    assert len(e.signals[0].values)==200
