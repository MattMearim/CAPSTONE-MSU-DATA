"""Deterministic engineering unit conversion, independent of AI providers.

Each unit uses ``canonical_value = value * scale + offset``. Prefix symbols
remain case-sensitive: mV and MV represent different voltage scales.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Number
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from frib_ds.models import EngineeringEvent


@dataclass(frozen=True)
class _Unit:
    symbol: str
    dimension: str
    canonical_unit: str
    scale: float = 1.0
    offset: float = 0.0
    aliases: tuple[str, ...] = ()


_UNITS = (
    _Unit("s", "time", "s", aliases=("sec", "second", "seconds")),
    _Unit("ms", "time", "s", 1e-3, aliases=("millisecond", "milliseconds")),
    _Unit("us", "time", "s", 1e-6, aliases=("microsecond", "microseconds", "µs", "μs")),
    _Unit("ns", "time", "s", 1e-9, aliases=("nanosecond", "nanoseconds")),
    _Unit("min", "time", "s", 60.0, aliases=("minute", "minutes")),
    _Unit("h", "time", "s", 3600.0, aliases=("hr", "hour", "hours")),
    _Unit("Hz", "frequency", "Hz", aliases=("hertz",)),
    _Unit("kHz", "frequency", "Hz", 1e3, aliases=("kilohertz",)),
    _Unit("MHz", "frequency", "Hz", 1e6, aliases=("megahertz",)),
    _Unit("GHz", "frequency", "Hz", 1e9, aliases=("gigahertz",)),
    _Unit("V", "voltage", "V", aliases=("volt", "volts")),
    _Unit("mV", "voltage", "V", 1e-3, aliases=("millivolt", "millivolts")),
    _Unit("kV", "voltage", "V", 1e3, aliases=("kilovolt", "kilovolts")),
    _Unit("MV", "voltage", "V", 1e6, aliases=("megavolt", "megavolts")),
    _Unit("V/m", "gradient", "V/m", aliases=("volt/m", "volts/m")),
    _Unit("kV/m", "gradient", "V/m", 1e3),
    _Unit("MV/m", "gradient", "V/m", 1e6),
    _Unit("W", "power", "W", aliases=("watt", "watts")),
    _Unit("mW", "power", "W", 1e-3, aliases=("milliwatt", "milliwatts")),
    _Unit("kW", "power", "W", 1e3, aliases=("kilowatt", "kilowatts")),
    _Unit("MW", "power", "W", 1e6, aliases=("megawatt", "megawatts")),
    _Unit("Pa", "pressure", "Pa", aliases=("pascal", "pascals")),
    _Unit("kPa", "pressure", "Pa", 1e3, aliases=("kilopascal", "kilopascals")),
    _Unit("MPa", "pressure", "Pa", 1e6, aliases=("megapascal", "megapascals")),
    _Unit("bar", "pressure", "Pa", 1e5),
    _Unit("mbar", "pressure", "Pa", 100.0, aliases=("millibar", "millibars")),
    _Unit("Torr", "pressure", "Pa", 101325.0 / 760.0, aliases=("torr",)),
    _Unit("mTorr", "pressure", "Pa", 101325.0 / 760000.0, aliases=("millitorr",)),
    _Unit("psi", "pressure", "Pa", 6894.757293168),
    _Unit("m", "length", "m", aliases=("meter", "meters", "metre", "metres")),
    _Unit("cm", "length", "m", 1e-2, aliases=("centimeter", "centimeters", "centimetre", "centimetres")),
    _Unit("mm", "length", "m", 1e-3, aliases=("millimeter", "millimeters", "millimetre", "millimetres")),
    _Unit("um", "length", "m", 1e-6, aliases=("micrometer", "micrometers", "micrometre", "micrometres", "µm", "μm")),
    _Unit("m/s^2", "acceleration", "m/s^2", aliases=("m/s²", "m/s2")),
    _Unit("g", "acceleration", "m/s^2", 9.80665, aliases=("standard gravity",)),
    _Unit("m/s", "velocity", "m/s"),
    _Unit("mm/s", "velocity", "m/s", 1e-3),
    _Unit("K", "temperature", "K", aliases=("kelvin", "kelvins")),
    _Unit("C", "temperature", "K", 1.0, 273.15, aliases=("°C", "degC", "celsius", "degrees Celsius")),
    _Unit("F", "temperature", "K", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0, aliases=("°F", "degF", "fahrenheit", "degrees Fahrenheit")),
    _Unit("delta_K", "temperature_difference", "delta_K", aliases=("ΔK", "deltaK", "delta kelvin")),
    _Unit("delta_C", "temperature_difference", "delta_K", aliases=("Δ°C", "deltaC", "delta Celsius")),
    _Unit("delta_F", "temperature_difference", "delta_K", 5.0 / 9.0, aliases=("Δ°F", "deltaF", "delta Fahrenheit")),
    _Unit("1", "dimensionless", "1", aliases=("", "dimensionless", "unitless", "fraction", "normalized")),
    _Unit("%", "dimensionless", "1", 0.01, aliases=("percent", "percentage", "pct")),
    _Unit("counts/s", "count_rate", "counts/s", aliases=("count/s", "cps", "counts per second")),
)
_BY_SYMBOL = {unit.symbol: unit for unit in _UNITS}


def _clean_unit(value: str) -> str:
    text=value.strip().replace("µ", "u").replace("μ", "u").replace("²", "^2")
    # Collapse whitespace once before removing single spaces at separators.
    # Searching for an absent separator with a leading \s* is quadratic.
    text=re.sub(r"\s+", " ", text)
    return re.sub(r" ?([/^]) ?", r"\1", text)


_ALIASES = {_clean_unit(alias): unit.symbol for unit in _UNITS for alias in (unit.symbol, *unit.aliases)}
# Full word aliases are forgiving; SI symbols and prefixes are always exact.
_WORD_ALIASES = {_clean_unit(alias).casefold(): unit.symbol for unit in _UNITS for alias in unit.aliases
                 if len(alias)>3 and re.fullmatch(r"[A-Za-z ]+", alias)}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUMBER_PREFIX = re.compile(_NUMBER)


def quantity_parts(value: str) -> tuple[str, str] | None:
    """Lex a number and optional unit in linear time, without accepting either.

    Ambiguous whitespace quantifiers around a lazy unit regex can backtrack
    cubically on a short, malformed multiline CSV cell. Parse the numeric prefix
    once, then trim and inspect the remainder before semantic validation.
    """
    text=value.strip()
    match=_NUMBER_PREFIX.match(text)
    if match is None: return None
    suffix=text[match.end():].strip()
    if "\n" in suffix: return None
    return match.group(0),suffix


def unit_catalog() -> list[dict[str, Any]]:
    """Return a fresh, JSON-ready catalog grouped by each unit's dimension."""
    return [{"symbol":unit.symbol, "dimension":unit.dimension, "canonical_unit":unit.canonical_unit,
             "scale":unit.scale, "offset":unit.offset, "aliases":list(unit.aliases)} for unit in _UNITS]


def normalize_unit(unit: str) -> str:
    """Resolve a supported label while retaining its scale, e.g. µs -> us."""
    if not isinstance(unit, str): raise ValueError("Unit must be a string; choose a supported unit from the unit catalog")
    cleaned=_clean_unit(unit)
    if cleaned in _ALIASES: return _ALIASES[cleaned]
    if cleaned.casefold() in _WORD_ALIASES: return _WORD_ALIASES[cleaned.casefold()]
    raise ValueError(f"Unknown unit {unit!r}. Choose a supported unit from the unit catalog; unit prefixes are case-sensitive (mV and MV differ).")


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (Number, str)):
        raise ValueError("Quantity must be a finite number; booleans, missing values and structured objects are not numeric measurements")
    if isinstance(value, str) and not re.fullmatch(_NUMBER, value.strip()):
        raise ValueError("Quantity must contain a finite decimal or scientific number; use parse_quantity for a value with a unit")
    try: number=float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Quantity must be a finite real number") from exc
    if not math.isfinite(number): raise ValueError("Quantity must be finite; NaN, infinity and overflowing numbers are not supported")
    return number


def parse_quantity(value: Any, default_unit: str = "") -> tuple[float, str]:
    """Parse a numeric scalar or '1.5 kV', returning value and source unit.

    An explicit suffix overrides the default. No suffix and no default means
    dimensionless; event normalization separately preserves legacy blank units.
    """
    if isinstance(value, str):
        parts=quantity_parts(value)
        if parts is None: raise ValueError("Quantity is missing a finite number. Enter a decimal/scientific value such as '1.5 kV' or '2e-3 s'.")
        number=_finite_number(parts[0])
        return number,normalize_unit(parts[1] or default_unit)
    return _finite_number(value),normalize_unit(default_unit)


def convert_value(value: Any, source: str, target: str) -> float:
    """Convert finite numeric values between units of the same dimension."""
    number=_finite_number(value)
    source_symbol=normalize_unit(source); target_symbol=normalize_unit(target)
    source_unit=_BY_SYMBOL[source_symbol]; target_unit=_BY_SYMBOL[target_symbol]
    if source_unit.dimension != target_unit.dimension:
        missing=" The source unit is missing; specify its physical unit." if not source.strip() else ""
        raise ValueError(f"Incompatible units: {source_symbol} ({source_unit.dimension}) cannot convert to {target_symbol} ({target_unit.dimension}). Choose units from the same dimension.{missing}")
    if source_symbol==target_symbol: return number
    converted=(number*source_unit.scale+source_unit.offset-target_unit.offset)/target_unit.scale
    if not math.isfinite(converted): raise ValueError("Converted quantity exceeds finite numeric range; check the value and selected units")
    return converted


def normalize_event_units(event: EngineeringEvent) -> EngineeringEvent:
    """Deep-copy an event and convert known signal units to canonical SI.

    Unknown and missing legacy labels retain their original values and labels,
    with explicit warnings. Source evidence and timestamps are never changed.
    """
    normalized=event.model_copy(deep=True)
    entries=[]; warnings=[]
    for signal in normalized.signals:
        original=signal.unit
        if not original.strip():
            entry={"signal":signal.name,"original_unit":original,"target_unit":original,"dimension":None,
                   "scale":1.0,"offset":0.0,"status":"missing_preserved"}
            warnings.append(f"Signal {signal.name!r} has no specified unit; its label and values were preserved. Assign a physical unit before dimensional comparisons.")
        else:
            try: source=_BY_SYMBOL[normalize_unit(original)]
            except ValueError:
                entry={"signal":signal.name,"original_unit":original,"target_unit":original,"dimension":None,
                       "scale":1.0,"offset":0.0,"status":"unknown_preserved"}
                warnings.append(f"Signal {signal.name!r} uses unknown unit {original!r}; its label and values were preserved without conversion. Choose a supported unit to enable dimensional comparisons.")
            else:
                target=source.canonical_unit
                signal.values=[convert_value(value,source.symbol,target) for value in signal.values]
                signal.unit=target
                entry={"signal":signal.name,"original_unit":original,"target_unit":target,"dimension":source.dimension,
                       "scale":source.scale,"offset":source.offset,"status":"converted" if source.symbol!=target else "unchanged"}
                previous=signal.metadata.get("unit_conversion")
                if source.symbol==target and isinstance(previous,dict) and previous.get("target_unit")==target:
                    entry=dict(previous)
        signal.metadata["unit_conversion"]=dict(entry)
        entries.append(entry)
    normalized.metadata["unit_normalization"]={"policy":"SI_known_preserve_unknown","signals":entries,"warnings":warnings}
    return normalized
