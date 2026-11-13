"""Conservative L2 quality checks, expressed as observations and review prompts."""
from __future__ import annotations

import hashlib
import math
import struct

from frib_ds.units import normalize_unit
from .common import DETAIL_LIMIT, make_issue, make_report

_TOP_KEYS={"expected_interval_s","gap_factor","channels","required_channels"}
_CHANNEL_KEYS={"expected_interval_s","expected_stable","stability_tolerance","min","max","flatline_samples"}


def default_expectations()->dict:
    return {"gap_factor":1.8,"channels":{},"required_channels":[]}


def _number(value,name,*,positive=False,nonnegative=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f"{name} must be a finite number, not a boolean or text")
    try: result=float(value)
    except (OverflowError,ValueError) as exc: raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result): raise ValueError(f"{name} must be finite")
    if positive and result<=0: raise ValueError(f"{name} must be greater than zero")
    if nonnegative and result<0: raise ValueError(f"{name} must not be negative")
    return result


def validate_expectations(expectations:dict|None=None)->dict:
    """Validate user settings in stored SI units and return an independent copy.

    Stability checks require an explicitly chosen absolute tolerance. Unknown
    keys are rejected so misspelled expectations cannot silently be ignored.
    """
    if expectations is None: return default_expectations()
    if not isinstance(expectations,dict): raise ValueError("Quality expectations must be a JSON object")
    unknown=set(expectations)-_TOP_KEYS
    if unknown: raise ValueError(f"Unknown quality settings: {', '.join(sorted(map(str,unknown)))}")
    result=default_expectations()
    if "gap_factor" in expectations:
        result["gap_factor"]=_number(expectations["gap_factor"],"gap_factor",positive=True)
        if result["gap_factor"]<=1: raise ValueError("gap_factor must be greater than one")
    if "expected_interval_s" in expectations:
        result["expected_interval_s"]=_number(expectations["expected_interval_s"],"expected_interval_s",positive=True)
    required=expectations.get("required_channels",[])
    if not isinstance(required,list) or any(not isinstance(name,str) or not name.strip() for name in required):
        raise ValueError("required_channels must be a list of nonempty channel names")
    if len(set(required))!=len(required): raise ValueError("required_channels must not contain duplicate names")
    result["required_channels"]=list(required)
    channels=expectations.get("channels",{})
    if not isinstance(channels,dict): raise ValueError("channels must map channel names to expectation objects")
    for name,settings in channels.items():
        if not isinstance(name,str) or not name.strip() or not isinstance(settings,dict):
            raise ValueError("Each channel needs a nonempty name and an expectation object")
        unknown=set(settings)-_CHANNEL_KEYS
        if unknown: raise ValueError(f"Unknown settings for channel {name!r}: {', '.join(sorted(map(str,unknown)))}")
        parsed={}
        for key in ("expected_interval_s","stability_tolerance","min","max"):
            if key in settings:
                parsed[key]=_number(settings[key],f"channels.{name}.{key}",positive=key=="expected_interval_s",nonnegative=key=="stability_tolerance")
        if "expected_stable" in settings:
            if not isinstance(settings["expected_stable"],bool): raise ValueError(f"channels.{name}.expected_stable must be true or false")
            parsed["expected_stable"]=settings["expected_stable"]
        if parsed.get("expected_stable") and "stability_tolerance" not in parsed:
            raise ValueError(f"Set channels.{name}.stability_tolerance explicitly when expected_stable is true")
        if "min" in parsed and "max" in parsed and parsed["min"]>parsed["max"]:
            raise ValueError(f"channels.{name}.min must not exceed max")
        if "flatline_samples" in settings:
            value=settings["flatline_samples"]
            if isinstance(value,bool) or not isinstance(value,int) or value<2:
                raise ValueError(f"channels.{name}.flatline_samples must be an integer of at least two")
            parsed["flatline_samples"]=value
        result["channels"][name]=parsed
    return result


def _median(values):
    ordered=sorted(values); length=len(ordered)
    if not length: return 0.0
    if length%2: return ordered[length//2]
    return ordered[length//2-1]/2+ordered[length//2]/2


def _locations(indices,times):
    indices=indices[:DETAIL_LIMIT]
    return {"rows":[index+1 for index in indices],"timestamps_s":[times[index] for index in indices]}


def _issue(code,title,message,name=None,indices=None,times=None,count=None,suggestion="",severity="warning"):
    locations=_locations(indices or [],times or []) if indices else {}
    return make_issue(code,severity,title,message,column=name,count=count,suggestion=suggestion,**locations)


def _fingerprint(signal):
    digest=hashlib.sha256(signal.unit.encode("utf-8"))
    for timestamp,value in zip(signal.timestamps_s,signal.values):
        digest.update(struct.pack("!dd",timestamp+0.0,value+0.0))
    return digest.digest()


def assess_event(event,expectations:dict|None=None)->dict:
    settings=validate_expectations(expectations)
    issues=[]; timing=[]; signatures={}
    ordinal=event.metadata.get("import_summary",{}).get("time_basis")=="row_index"
    available={signal.name for signal in event.signals}|{state.name for state in event.states}
    missing=[name for name in settings["required_channels"] if name not in available]
    if missing:
        issues.append(_issue("MISSING_CHANNEL","Expected channels are absent",f"The capture does not contain expected channels: {', '.join(missing)}. Capture scope may be intentional.",count=len(missing),suggestion="Confirm the intended capture channels or import the missing evidence."))
    unmatched=[name for name in settings["channels"] if name not in available]
    if unmatched:
        issues.append(_issue("UNMATCHED_EXPECTATION","Channel settings did not match recorded evidence",f"Settings name channels absent from this capture: {', '.join(unmatched)}. Those settings could not be assessed.",count=len(unmatched),suggestion="Check channel spelling and mapping, or confirm that the expected channels were not captured."))
    if not event.signals:
        issues.append(_issue("NO_NUMERIC_SIGNALS","No numeric channels to assess","The event contains categorical or narrative evidence only; numeric quality checks were not applied.",severity="info",suggestion="Review state and text evidence, or add measured channels if numeric checks are required."))
    for signal in event.signals:
        name=signal.name; values=signal.values; times=signal.timestamps_s
        channel=settings["channels"].get(name,{})
        if not signal.unit.strip():
            issues.append(_issue("UNSPECIFIED_UNIT","Measurement unit is unspecified","Values were preserved without assuming a physical dimension.",name,suggestion="Assign the recorded unit explicitly; do not infer it from the channel name."))
        else:
            try: normalize_unit(signal.unit)
            except ValueError:
                issues.append(_issue("UNKNOWN_UNIT","Measurement unit is unsupported",f"Unit {signal.unit!r} was preserved; dimensional conversion cannot be verified.",name,suggestion="Confirm the source unit and choose a supported compatible unit."))
        invalid_values=[index for index,value in enumerate(values) if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)]
        if invalid_values:
            issues.append(_issue("NONFINITE_VALUES","Numeric values are invalid","Nonfinite or nonnumeric values prevent reliable numerical assessment; nothing was filled or replaced.",name,invalid_values,times if len(times)==len(values) else [0.0]*len(values),len(invalid_values),"Correct the original source or explicitly exclude invalid samples.","error"))
            continue
        invalid_times=[index for index,time in enumerate(times) if isinstance(time,bool) or not isinstance(time,(int,float)) or not math.isfinite(time) or (index and time<=times[index-1])]
        if len(times)!=len(values) or len(values)<2 or invalid_times:
            issues.append(_issue("INVALID_TIMESTAMPS","Samples lack a valid time coordinate","Numeric samples need equal value/time lengths and at least two finite, strictly increasing time coordinates.",name,count=max(len(invalid_times),1),suggestion="Correct or explicitly remap the source timestamps; no values were filled.",severity="error"))
            continue
        magnitude=max(abs(value) for value in values)
        scaled=[value/magnitude for value in values] if magnitude else [0.0]*len(values)
        deltas=[scaled[index]-scaled[index-1] for index in range(1,len(values))]
        center=_median(deltas)
        noise=1.4826*_median([abs(value-center) for value in deltas])
        threshold=max(8*noise,8*_median([abs(value) for value in deltas]),1e-12)
        skipped=signal.metadata.get("blank_cells_skipped",0)
        if isinstance(skipped,int) and not isinstance(skipped,bool) and skipped>0:
            issues.append(_issue("BLANK_VALUES_SKIPPED","Blank source measurements were omitted",f"The importer recorded {skipped} blank cells omitted from this channel. Missing values were not filled.",name,count=skipped,suggestion="Review original blank cells and capture coverage before using derived statistics.",severity="info"))
        skipped=signal.metadata.get("invalid_cells_skipped",0)
        if isinstance(skipped,int) and not isinstance(skipped,bool) and skipped>0:
            issues.append(_issue("INVALID_VALUES_SKIPPED","Invalid source measurements were excluded",f"The importer explicitly excluded {skipped} invalid cells from this channel.",name,count=skipped,suggestion="Review the source rows and exclusion policy before relying on this channel."))
        if "min" in channel or "max" in channel:
            outside=[index for index,value in enumerate(values) if ("min" in channel and value<channel["min"]) or ("max" in channel and value>channel["max"])]
            if outside:
                issues.append(_issue("OUT_OF_BOUNDS","Values exceed user expectations","Recorded values fall outside the user-supplied bounds in stored SI units. These may be real operating changes; the check does not prove corruption.",name,outside,times,len(outside),"Verify the expected bounds and compare the original measurements with event context."))
        if channel.get("expected_stable"):
            baseline=_median(scaled[:min(25,max(1,len(values)//10))])
            tolerance=channel["stability_tolerance"]/magnitude if magnitude else math.inf
            unstable=[index for index,value in enumerate(scaled) if abs(value-baseline)>tolerance]
            if unstable:
                issues.append(_issue("STABILITY_EXCEEDED","Expected stability tolerance was exceeded","Values depart from the initial median baseline by more than the absolute user-set tolerance in stored SI units. A genuine change is possible.",name,unstable,times,len(unstable),"Confirm that stability was expected throughout this capture and review the observed change."))
        runs=[]; start=0; minimum=channel.get("flatline_samples",5)
        for index in range(1,len(values)+1):
            if index==len(values) or values[index]!=values[start]:
                if index-start>=minimum: runs.append(start)
                start=index
        if runs:
            issues.append(_issue("FLATLINE_RUN","Potential constant or stuck readings",f"There are {len(runs)} runs of at least {minimum} exactly repeated samples. A genuinely stable or quantized measurement can produce this pattern; sensor failure is not established.",name,runs,times,len(runs),"Compare instrument resolution, operating state and independent measurements before treating the channel as stuck."))
        spikes=[]
        if len(values)>=7:
            for index in range(1,len(values)-1):
                before=scaled[index]-scaled[index-1]; after=scaled[index+1]-scaled[index]
                residual=abs(scaled[index]-(scaled[index-1]/2+scaled[index+1]/2))
                if before*after<0 and min(abs(before),abs(after))>threshold and abs(scaled[index+1]-scaled[index-1])<=max(2*noise,residual*.25):
                    spikes.append(index)
        if spikes:
            issues.append(_issue("ISOLATED_SPIKE","Possible isolated excursions","Isolated values differ sharply from both neighboring samples relative to the robust first-difference scale. Real transients are possible; values were retained.",name,spikes,times,len(spikes),"Inspect the original waveform and correlated channels before excluding any excursion."))
        spike_neighbors={index for spike in spikes for index in (spike,spike+1)}
        steps=[]; window=min(15,max(2,len(values)//20))
        for index in range(window,len(values)-window+1):
            if index in spike_neighbors or abs(deltas[index-1])<=threshold: continue
            before=_median(scaled[index-window:index]); after=_median(scaled[index:index+window])
            if abs(after-before)>threshold: steps.append(index)
        if steps:
            issues.append(_issue("BASELINE_CHANGE","Possible abrupt baseline changes","Adjacent samples and neighboring median windows indicate an abrupt sustained change. This may be a real process transition rather than a recording problem.",name,steps,times,len(steps),"Compare timestamps with state changes, configuration updates and independent channels."))
        boundary=[index for index in range(1,len(values)) if (index<=2 or index>=len(values)-2)
                  and index not in spike_neighbors and index not in steps and abs(deltas[index-1])>threshold]
        if boundary:
            issues.append(_issue("BOUNDARY_JUMP","Abrupt change near a capture boundary","A robustly large adjacent change occurs within two samples of a capture boundary. Neighboring context is insufficient to classify it; a genuine event or truncated capture is possible. All measurements were retained.",name,boundary,times,len(boundary),"Compare the original capture and state logs, and extend the recording window if available before excluding any boundary measurement."))
        signature=_fingerprint(signal)
        if signature in signatures:
            first=signatures[signature]
            if values==first.values and times==first.timestamps_s and signal.unit==first.unit:
                issues.append(_issue("DUPLICATE_SIGNAL_DATA","Channels contain identical samples",f"This channel exactly matches {first.name!r} in values, timestamps and unit. Mirrored channels can be intentional.",name,count=len(values),suggestion="Confirm channel mapping and whether these are independent measurements."))
        else: signatures[signature]=signal
        inferred=ordinal or signal.metadata.get("inferred_time") is True
        if inferred:
            issues.append(_issue("TIMING_UNAVAILABLE","Elapsed timing is unavailable","Time coordinates represent record order, not measured seconds. Gap, cadence and sample-rate checks were skipped.",name,severity="info",suggestion="Supply recorded timestamps before interpreting intervals or frequency spectra."))
            continue
        intervals=[times[index]-times[index-1] for index in range(1,len(times))]
        finite_intervals=[value for value in intervals if math.isfinite(value) and value>0]
        typical=_median(finite_intervals)
        explicit=channel.get("expected_interval_s",settings.get("expected_interval_s"))
        reference=explicit or typical
        if reference>0:
            gap_threshold=1.5 if explicit is not None else settings["gap_factor"]
            gaps=[index+1 for index,value in enumerate(intervals) if value/reference>=gap_threshold]
            if gaps:
                code="RECORDING_GAP" if explicit is not None else "POTENTIAL_RECORDING_GAP"
                title="Expected recording intervals were exceeded" if explicit is not None else "Potential gaps in recording"
                message=("Observed intervals are at least 1.5 times the user-set expected interval (50% jitter allowance). The interval violation is confirmed; it does not prove that physical samples were lost." if explicit is not None else "Observed intervals are unusually large relative to the median recorded cadence. Irregular or intentional acquisition can explain this pattern; missing samples are not confirmed.")
                issue=_issue(code,title,message,name,gaps,times,len(gaps),"Inspect acquisition timing and the original source; do not fill missing intervals automatically.")
                issue["intervals"]=[]
                for index in gaps[:DETAIL_LIMIT]:
                    duration=intervals[index-1]
                    interval={"start_s":times[index-1],"end_s":times[index],"observed_interval_s":duration if math.isfinite(duration) else None}
                    interval["expected_interval_s" if explicit is not None else "reference_interval_s"]=reference
                    if not math.isfinite(duration): interval["duration_note"]="Difference exceeds finite numeric range"
                    ratio=duration/reference
                    if explicit is not None and math.isfinite(ratio) and ratio<=1_000_000:
                        interval["estimated_missing_samples"]=max(0,round(ratio)-1)
                    issue["intervals"].append(interval)
                issues.append(issue)
            timing.append((signal,reference))
        if typical>0 and len(intervals)>=3:
            irregular=[index+1 for index,value in enumerate(intervals) if abs(value/typical-1)>.1]
            if len(irregular)/len(intervals)>.2:
                issues.append(_issue("IRREGULAR_CADENCE","Recording cadence is irregular","More than 20% of observed intervals differ from the median cadence by over 10%. Uneven sampling can be intentional; uniform resampling or spectra need review.",name,irregular,times,len(irregular),"Confirm the acquisition scheme before assuming a uniform sample interval."))
        declared=signal.sample_rate_hz
        if typical>0 and isinstance(declared,(int,float)) and not isinstance(declared,bool) and math.isfinite(declared) and declared>0:
            ratio=typical/(1.0/declared)
            if abs(ratio-1)>.02:
                issues.append(_issue("SAMPLE_RATE_MISMATCH","Declared sample rate differs from timestamps","The median timestamp interval differs by more than 2% from the declared sample-rate interval. Neither source was silently preferred or rewritten.",name,suggestion="Confirm the recorded timestamps and sample-rate declaration before frequency analysis."))
    if len(timing)>1:
        earliest=min(signal.timestamps_s[0] for signal,_ in timing)
        latest=max(signal.timestamps_s[-1] for signal,_ in timing)
        for signal,reference in timing:
            locations=[]
            if (signal.timestamps_s[0]-earliest)/reference>settings["gap_factor"]: locations.append(0)
            if (latest-signal.timestamps_s[-1])/reference>settings["gap_factor"]: locations.append(len(signal.values)-1)
            if locations:
                issues.append(_issue("CHANNEL_COVERAGE","Channel covers a shorter recording interval","This channel starts later or ends earlier than other measured channels by more than the selected cadence threshold. Different capture windows can be intentional.",signal.name,locations,signal.timestamps_s,len(locations),"Confirm channel capture windows before comparing or aligning measurements."))
    references=[reference for _,reference in timing]
    reference=settings.get("expected_interval_s") or (_median(references) if references else None)
    if not ordinal:
        grouped={}
        for state in event.states: grouped.setdefault(state.name,[]).append(state)
        for name,states in grouped.items():
            states=sorted(states,key=lambda state:state.timestamp_s)
            cadence=settings["channels"].get(name,{}).get("expected_interval_s",reference)
            if not cadence or len(states)<6: continue
            rapid=[index for index in range(2,len(states)) if states[index].value==states[index-2].value!=states[index-1].value and 0<=states[index].timestamp_s-states[index-1].timestamp_s<=cadence]
            if len(rapid)>=4:
                issues.append(_issue("CATEGORY_CHATTER","Possible rapid alternating state changes","Repeated alternating categories occur at or faster than the reference recording cadence. These may be legitimate transitions; chatter or equipment failure is not established.",name,rapid,[state.timestamp_s for state in states],len(rapid),"Compare the state sequence with the expected control behavior and independent logs."))
    report=make_report("L2",issues)
    report["expectations"]=settings
    report["location_basis"]="accepted_sample_index"
    return report
