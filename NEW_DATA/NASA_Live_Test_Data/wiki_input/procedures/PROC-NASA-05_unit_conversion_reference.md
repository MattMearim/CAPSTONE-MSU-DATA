# Unit conversion reference for the NASA data set - NASA-1

TRAINING PROCEDURE - written for testing the FRIB decision-support system with public NASA data. Not a FRIB operating procedure.

Version: NASA-1 (2026-11-17)

## Purpose
Convert the non-standard units in the NASA data set consistently.

| Quantity | Unit in file | Conversion |
|---|---|---|
| Distance | au | 1 au = 149,597,870.7 km |
| Distance | lunar distance (LD) | 1 LD = 384,400 km = 0.002569555 au |
| Energy | 1e10 J | value x 10^10 J |
| Energy | kt (kiloton TNT) | 1 kt = 4.184 x 10^12 J |
| Brightness | mag (absolute magnitude H) | logarithmic; lower = brighter/larger |
| Angle | deg | degrees |
| Pressure | kPa | 1 kPa = 1,000 Pa |
| Temperature | C | K = C + 273.15; F = C x 9/5 + 32 |
| Solar energy | kWh/m^2/day | 1 kWh = 3.6 MJ |

Used by: [PROC-NASA-01](PROC-NASA-01_power_weather_review.md), [PROC-NASA-02](PROC-NASA-02_fireball_record_review.md), [PROC-NASA-03](PROC-NASA-03_close_approach_review.md).

## References
- [NIST - SI units](https://www.nist.gov/pml/owm/metric-si/si-units)
- [SBDB Close-Approach Data API (au and LD fields)](https://ssd-api.jpl.nasa.gov/doc/cad.html)
- [Fireball Data API (energy fields)](https://ssd-api.jpl.nasa.gov/doc/fireball.html)
