from __future__ import annotations

from decimal import Decimal
import math

import pytest

from frib_ds.models import EngineeringEvent, Provenance, Signal
from frib_ds.units import convert_value, normalize_event_units, normalize_unit, parse_quantity, unit_catalog


@pytest.mark.parametrize("value,source,target,expected",[
    (2,"min","s",120),(2,"h","min",120),(250,"ms","s",.25),(1,"us","ns",1000),
    (1.5,"GHz","MHz",1500),(2,"kHz","Hz",2000),
    (1,"mV","V",.001),(1,"MV","V",1e6),(1.5,"kV","V",1500),
    (2,"MV/m","V/m",2e6),(2,"kV/m","V/m",2000),
    (3,"mW","W",.003),(1.5,"kW","W",1500),(2,"MW","W",2e6),
    (2,"bar","Pa",2e5),(1,"mbar","Pa",100),(2,"MPa","kPa",2000),
    (760,"Torr","Pa",101325),(1,"mTorr","Torr",.001),(1,"psi","Pa",6894.757293168),
    (2,"cm","m",.02),(4,"mm","um",4000),(1,"g","m/s^2",9.80665),
    (25,"mm/s","m/s",.025),(50,"%","fraction",.5),(.5,"1","%",50),
    (100,"counts/s","cps",100),
    (0,"C","K",273.15),(32,"F","C",0),(212,"F","K",373.15),
    (-40,"C","F",-40),(273.15,"K","C",0),
    (10,"delta_C","delta_K",10),(18,"delta_F","delta_K",10),
    (-10,"delta_K","delta_F",-18),
])
def test_supported_physical_conversions(value,source,target,expected):
    assert convert_value(value,source,target)==pytest.approx(expected)
    assert convert_value(convert_value(value,source,target),target,source)==pytest.approx(value,abs=1e-10)


@pytest.mark.parametrize("label,expected",[("µs","us"),("μm","um"),("m / s²","m/s^2"),(" °C ","C"),("degrees Fahrenheit","F"),("MILLIVOLTS","mV"),("normalized","1"),("fraction","1"),("","1"),("mV","mV"),("MV","MV"),("Δ°C","delta_C"),("Δ°F","delta_F"),("ΔK","delta_K")])
def test_normalization_preserves_prefix_case(label,expected):
    assert normalize_unit(label)==expected


@pytest.mark.parametrize("value,default,expected",[("1.5 kV","",(1.5,"kV")),("-2.3e-4MV/m","",(-2.3e-4,"MV/m")),(".5 %","",(.5,"%")),("+1.E3 µs","",(1000,"us")),("2.5","mbar",(2.5,"mbar")),("2.5 kPa","bar",(2.5,"kPa")),(Decimal("1.5"),"V",(1.5,"V")),(5,"",(5,"1"))])
def test_quantity_parser(value,default,expected):
    assert parse_quantity(value,default)==expected


@pytest.mark.parametrize("value",[True,False,None,[],{},complex(1,2),float("nan"),float("inf"),-float("inf"),"NaN","inf","1e999","", "kV","one V","1,5 V"])
def test_non_measurements_are_rejected(value):
    with pytest.raises(ValueError): parse_quantity(value)
    with pytest.raises(ValueError): convert_value(value,"V","mV")


@pytest.mark.parametrize("label",["mv","KV","mhz","Mbar","MTorr","dB","dBm","arb","banana"])
def test_unknown_units_are_actionable(label):
    with pytest.raises(ValueError,match="Unknown unit.*catalog"):
        normalize_unit(label)


@pytest.mark.parametrize("source,target",[("V","W"),("m","s"),("g","m/s"),("counts/s","Hz"),("C","Pa"),("","V"),("C","delta_K"),("delta_C","K"),("delta_F","F")])
def test_incompatible_dimensions_are_rejected(source,target):
    with pytest.raises(ValueError,match="Incompatible units.*same dimension"):
        convert_value(1,source,target)


def test_conversion_overflow_is_rejected():
    with pytest.raises(ValueError,match="finite numeric range"):
        convert_value(1e308,"MV","mV")


def test_catalog_is_independent_and_every_entry_round_trips():
    catalog=unit_catalog()
    assert len({item["symbol"] for item in catalog})==len(catalog)
    for item in catalog:
        value=convert_value(1.234,item["symbol"],item["canonical_unit"])
        assert math.isfinite(value)
        assert convert_value(value,item["canonical_unit"],item["symbol"])==pytest.approx(1.234)
    catalog[0]["aliases"].append("mutated")
    assert "mutated" not in unit_catalog()[0]["aliases"]


def make_event():
    return EngineeringEvent(event_id="UNITS-1",domain="mechanical",event_type="capture",
        metadata={"operator":{"note":"preserve source"}},provenance=Provenance(source="import"),
        signals=[Signal(name=name,unit=unit,sample_rate_hz=10,timestamps_s=[0,.1],values=values)
                 for name,unit,values in [("voltage","mV",[1000,2000]),("temperature","C",[0,100]),("vibration","g",[1,2]),("legacy","arb",[1,2]),("missing","",[3,4]),("normalized","normalized",[.5,1])]])


def test_event_conversion_preserves_original_and_documents_warnings():
    original=make_event(); before=original.model_dump()
    result=normalize_event_units(original)
    assert original.model_dump()==before
    assert result.signals[0].unit=="V" and result.signals[0].values==[1,2]
    assert result.signals[1].unit=="K" and result.signals[1].values==pytest.approx([273.15,373.15])
    assert result.signals[2].unit=="m/s^2" and result.signals[2].values==pytest.approx([9.80665,19.6133])
    assert result.signals[3].unit=="arb" and result.signals[3].values==[1,2]
    assert result.signals[4].unit=="" and result.signals[4].values==[3,4]
    assert result.signals[5].unit=="1"
    assert result.signals[0].metadata["unit_conversion"]["original_unit"]=="mV"
    assert result.metadata["unit_normalization"]["signals"][3]["status"]=="unknown_preserved"
    assert len(result.metadata["unit_normalization"]["warnings"])==2
    assert result.signals[0].timestamps_s==original.signals[0].timestamps_s
    result.metadata["operator"]["note"]="changed copy"
    assert original.metadata["operator"]["note"]=="preserve source"


def test_event_conversion_is_idempotent_and_keeps_original_units():
    once=normalize_event_units(make_event()); twice=normalize_event_units(once)
    assert twice.model_dump()==once.model_dump()


def test_temperature_differences_have_no_offset_and_names_do_not_infer_units():
    event=EngineeringEvent(event_id="TEMP-DIFFERENCES",domain="evidence",event_type="capture",
        provenance=Provenance(source="import"),signals=[
            Signal(name="measured_change",unit="Δ°F",sample_rate_hz=1,timestamps_s=[0,1],values=[18,-9]),
            Signal(name="temperature_change",unit="C",sample_rate_hz=1,timestamps_s=[0,1],values=[10,20])])
    result=normalize_event_units(event)
    assert result.signals[0].unit=="delta_K"
    assert result.signals[0].values==pytest.approx([10,-5])
    assert result.signals[0].metadata["unit_conversion"]["offset"]==0
    assert result.signals[1].unit=="K"
    assert result.signals[1].values==pytest.approx([283.15,293.15])
