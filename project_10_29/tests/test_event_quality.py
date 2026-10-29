from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest

from frib_ds.models import EngineeringEvent, Provenance, Signal, StateEvent
from frib_ds.quality import assess_event, default_expectations, validate_expectations
from frib_ds.quality.common import make_issue, make_report


def capture(values=None,times=None,unit="V",rate=10,metadata=None,name="voltage"):
    values=values if values is not None else [math.sin(index/10) for index in range(100)]
    times=times if times is not None else [index/rate for index in range(len(values))]
    return EngineeringEvent(event_id="QUALITY-1",domain="other",event_type="capture",metadata=metadata or {},
        signals=[Signal(name=name,unit=unit,sample_rate_hz=rate,timestamps_s=times,values=values)],provenance=Provenance(source="test"))


def by_code(report):
    return {issue["code"]:issue for issue in report["issues"]}


def test_good_capture_is_ok_and_assessment_does_not_mutate_evidence():
    event=capture(); before=event.model_dump()
    report=assess_event(event)
    assert report=={"version":"1.0","stage":"L2","status":"ok","summary":{"error":0,"warning":0,"info":0},"issues":[],"unit_suggestions":[],"expectations":default_expectations(),"location_basis":"accepted_sample_index"}
    assert event.model_dump()==before


def test_constant_readings_are_only_potential_stuck_sensor():
    event=capture([2.5]*20)
    issue=by_code(assess_event(event))["FLATLINE_RUN"]
    assert issue["count"]==1 and issue["rows"]==[1]
    assert "genuinely stable" in issue["message"] and "not established" in issue["message"]
    assert event.signals[0].values==[2.5]*20


def test_expected_dropout_and_estimated_cadence_have_different_certainty():
    event=capture([1,2,3,4,5],times=[0,.1,.2,.6,.7])
    expected=by_code(assess_event(event,{"expected_interval_s":.1}))
    estimated=by_code(assess_event(event))
    assert expected["RECORDING_GAP"]["count"]==1
    assert expected["RECORDING_GAP"]["rows"]==[4]
    assert expected["RECORDING_GAP"]["intervals"][0]["start_s"]==.2
    assert expected["RECORDING_GAP"]["intervals"][0]["end_s"]==.6
    assert expected["RECORDING_GAP"]["intervals"][0]["estimated_missing_samples"]==3
    assert "does not prove" in expected["RECORDING_GAP"]["message"]
    assert estimated["POTENTIAL_RECORDING_GAP"]["count"]==1
    assert "not confirmed" in estimated["POTENTIAL_RECORDING_GAP"]["message"]


def test_explicit_interval_detects_one_missing_record_without_estimated_gap_factor():
    event=capture([1,2,3],times=[0,3,4],rate=1)
    report=assess_event(event,{"expected_interval_s":1,"gap_factor":100})
    assert by_code(report)["RECORDING_GAP"]["count"]==1
    assert "POTENTIAL_RECORDING_GAP" not in by_code(report)


def test_one_missing_position_among_a_thousand_is_still_a_potential_gap():
    times=[index*.1 for index in range(1001) if index!=500]
    event=capture([index/1000 for index in range(1000)],times=times)
    issue=by_code(assess_event(event))["POTENTIAL_RECORDING_GAP"]
    assert issue["count"]==1 and issue["rows"]==[501]
    assert issue["intervals"][0]["start_s"]==pytest.approx(49.9)
    assert "estimated_missing_samples" not in issue["intervals"][0]


def test_irregular_acquisition_is_identified_without_asserting_missing_samples():
    event=capture([1,2,3,4,5,6],times=[0,1,2.4,3.4,4.8,5.8],rate=1)
    report=assess_event(event)
    issue=by_code(report)["IRREGULAR_CADENCE"]
    assert issue["count"]==2 and "intentional" in issue["message"]
    assert "RECORDING_GAP" not in by_code(report)


def test_declared_rate_mismatch_uses_timestamps_without_changing_them():
    event=capture([1,2,3,4,5],times=[0,1,2,3,4],rate=100)
    assert "SAMPLE_RATE_MISMATCH" in by_code(assess_event(event))
    assert event.signals[0].sample_rate_hz==100


def test_spike_and_sustained_step_are_not_conflated():
    spike=capture([0]*10+[10]+[0]*10)
    issues=by_code(assess_event(spike))
    assert issues["ISOLATED_SPIKE"]["rows"]==[11]
    assert "BASELINE_CHANGE" not in issues
    step=capture([0]*20+[10]*20)
    issues=by_code(assess_event(step))
    assert issues["BASELINE_CHANGE"]["rows"]==[21]
    assert "ISOLATED_SPIKE" not in issues
    assert "real process transition" in issues["BASELINE_CHANGE"]["message"]


def test_smooth_ramp_is_not_reported_as_abrupt_steps_or_isolated_spikes():
    issues=by_code(assess_event(capture([index/100 for index in range(100)])))
    assert "BASELINE_CHANGE" not in issues and "ISOLATED_SPIKE" not in issues
    assert "BOUNDARY_JUMP" not in issues


@pytest.mark.parametrize("values,row",[([1]*9+[10],10),([10]+[1]*9,2)])
def test_large_boundary_changes_are_reported_without_claiming_a_cause(values,row):
    issue=by_code(assess_event(capture(values)))["BOUNDARY_JUMP"]
    assert issue["count"]==1 and issue["rows"]==[row]
    assert issue["severity"]=="warning"
    assert "context is insufficient" in issue["message"] and "genuine event" in issue["message"]
    assert issue["timestamps_s"]==pytest.approx([(row-1)/10])


def test_boundary_steps_and_isolated_spikes_are_not_double_counted():
    step=by_code(assess_event(capture([1,1]+[10]*8)))
    assert "BASELINE_CHANGE" in step and "BOUNDARY_JUMP" not in step
    spike=by_code(assess_event(capture([1,10]+[1]*8)))
    assert "ISOLATED_SPIKE" in spike and "BOUNDARY_JUMP" not in spike


def test_user_stability_and_bounds_use_absolute_stored_si_values():
    event=capture([1,1,1,10,10,10])
    report=assess_event(event,{"channels":{"voltage":{"expected_stable":True,"stability_tolerance":.2,"min":0,"max":5}}})
    issues=by_code(report)
    assert issues["STABILITY_EXCEEDED"]["count"]==3
    assert issues["OUT_OF_BOUNDS"]["count"]==3
    assert issues["OUT_OF_BOUNDS"]["rows"]==[4,5,6]


def test_details_are_bounded_but_counts_cover_the_whole_capture():
    report=assess_event(capture([index for index in range(100)]),{"channels":{"voltage":{"max":0}}})
    issue=by_code(report)["OUT_OF_BOUNDS"]
    assert issue["count"]==99
    assert len(issue["rows"])==len(issue["timestamps_s"])==25


@pytest.mark.parametrize("unit,code",[("","UNSPECIFIED_UNIT"),("arb","UNKNOWN_UNIT")])
def test_missing_or_unknown_units_are_preserved_without_inference(unit,code):
    event=capture(unit=unit,name="pressure")
    assert code in by_code(assess_event(event))
    assert event.signals[0].unit==unit


def test_zero_values_do_not_mean_missing_values():
    issues=by_code(assess_event(capture([0,1,0,2,0,3,0])))
    assert "NONFINITE_VALUES" not in issues and "OUT_OF_BOUNDS" not in issues


def test_ordinal_time_skips_elapsed_checks_even_when_expectations_are_supplied():
    event=capture([1,2,3,4,5],times=[0,1,5,6,7],rate=100,metadata={"import_summary":{"time_basis":"row_index"}})
    issues=by_code(assess_event(event,{"expected_interval_s":.01}))
    assert "TIMING_UNAVAILABLE" in issues
    assert not ({"RECORDING_GAP","POTENTIAL_RECORDING_GAP","IRREGULAR_CADENCE","SAMPLE_RATE_MISMATCH"}&set(issues))


def test_identical_channels_and_shorter_coverage_are_flagged_separately():
    event=capture()
    copied=event.signals[0].model_copy(deep=True); copied.name="mirror"
    short=Signal(name="short",unit="V",sample_rate_hz=10,timestamps_s=[index/10 for index in range(20,70)],values=[index/3 for index in range(50)])
    event.signals.extend([copied,short])
    issues=by_code(assess_event(event))
    assert issues["DUPLICATE_SIGNAL_DATA"]["column"]=="mirror"
    assert issues["DUPLICATE_SIGNAL_DATA"]["count"]==100
    assert issues["CHANNEL_COVERAGE"]["column"]=="short"


def test_required_channels_and_skipped_cells_report_known_counts():
    event=capture()
    event.signals[0].metadata.update(blank_cells_skipped=7,invalid_cells_skipped=3)
    report=assess_event(event,{"required_channels":["pressure","voltage"]})
    issues=by_code(report)
    assert issues["MISSING_CHANNEL"]["count"]==1
    assert issues["BLANK_VALUES_SKIPPED"]["count"]==7 and issues["BLANK_VALUES_SKIPPED"]["severity"]=="info"
    assert issues["INVALID_VALUES_SKIPPED"]["count"]==3


def test_unmatched_channel_expectations_are_not_silently_ignored():
    report=assess_event(capture(),{"channels":{"voltag":{"min":0}}})
    issue=by_code(report)["UNMATCHED_EXPECTATION"]
    assert issue["count"]==1 and "voltag" in issue["message"]
    assert report["expectations"]["channels"]["voltag"]["min"]==0


def test_alternating_state_changes_are_possible_chatter_not_diagnosis():
    event=capture()
    event.states=[StateEvent(name="enabled",value="ON" if index%2 else "OFF",timestamp_s=index*.01) for index in range(10)]
    issue=by_code(assess_event(event))["CATEGORY_CHATTER"]
    assert issue["count"]==8 and "legitimate" in issue["message"]


def test_invalid_constructed_input_blocks_instead_of_claiming_quality():
    event=capture()
    event.signals[0].values[3]=float("nan")
    result=assess_event(event)
    assert result["status"]=="blocked" and by_code(result)["NONFINITE_VALUES"]["count"]==1
    event=capture(); event.signals[0].timestamps_s[3]=event.signals[0].timestamps_s[2]
    assert assess_event(event)["status"]=="blocked"


def test_large_finite_values_and_intervals_produce_finite_json_reports():
    event=capture([-1e308,-5e307,0,5e307,1e308],times=[-1e308,-5e307,0,5e307,1e308],rate=1e-308)
    report=assess_event(event,{"expected_interval_s":1e-308,"channels":{"voltage":{"expected_stable":True,"stability_tolerance":1e308}}})
    json.dumps(report,allow_nan=False)
    assert "RECORDING_GAP" in by_code(report)
    overflow=capture([1,2],times=[-1e308,1e308],rate=1)
    result=assess_event(overflow,{"expected_interval_s":1})
    json.dumps(result,allow_nan=False)
    assert by_code(result)["RECORDING_GAP"]["intervals"][0]["observed_interval_s"] is None


@pytest.mark.parametrize("settings",[
    [],{"typo":1},{"expected_interval_s":0},{"expected_interval_s":True},{"expected_interval_s":"1"},
    {"gap_factor":1},{"gap_factor":float("inf")},{"channels":[]},
    {"channels":{"v":{"unknown":1}}},{"channels":{"v":{"min":2,"max":1}}},
    {"channels":{"v":{"stability_tolerance":-1}}},{"channels":{"v":{"expected_stable":True}}},
    {"channels":{"v":{"expected_stable":"true"}}},{"channels":{"v":{"flatline_samples":1}}},
    {"channels":{"v":{"flatline_samples":True}}},{"channels":{"v":{"max":float("nan")}}},
    {"required_channels":"v"},{"required_channels":["v","v"]},{"required_channels":[""]},
])
def test_invalid_expectations_are_rejected(settings):
    with pytest.raises(ValueError): validate_expectations(settings)


def test_settings_are_independent_and_channel_interval_overrides_global():
    settings={"expected_interval_s":100,"channels":{"voltage":{"expected_interval_s":1,"flatline_samples":2}},"required_channels":["voltage"]}
    original=deepcopy(settings)
    report=assess_event(capture([1,2,3],times=[0,3,4],rate=1),settings)
    assert "RECORDING_GAP" in by_code(report) and settings==original
    validated=validate_expectations(settings); validated["channels"]["voltage"]["expected_interval_s"]=2
    assert settings==original
    defaults=default_expectations(); defaults["required_channels"].append("v")
    assert default_expectations()["required_channels"]==[]


def test_common_report_helpers_enforce_status_and_bound_locations():
    issue=make_issue("X","error","title","message",rows=list(range(100)),timestamps_s=list(range(100)),count=100)
    report=make_report("L1",[issue])
    assert report["status"]=="blocked" and report["summary"]=={"error":1,"warning":0,"info":0}
    assert len(issue["rows"])==25 and issue["count"]==100
