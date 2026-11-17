# Weather data review (NASA POWER, FRIB site) - NASA-1

TRAINING PROCEDURE - written for testing the FRIB decision-support system with public NASA data. Not a FRIB operating procedure.

Version: NASA-1 (2026-11-17)

## Purpose
Review the hourly and daily NASA POWER weather files for the FRIB site before using them as evidence.

## Inputs
- [power_frib_hourly.csv](../datasets/power_frib_hourly.csv) (UTC)
- [power_frib_daily.csv](../datasets/power_frib_daily.csv) (local solar time, LST)
- Definitions: [data_dictionary.md](../documents/data_dictionary.md)

## Steps
1. Check for the fill value **-999**. It means "no data", not a measurement. Exclude it from averages, minimums and totals. See the POWER [daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/).
2. Check the time standard before comparing the two files. The hourly file is UTC ([hourly API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)); the daily file is local solar time. A "day" in one file is not the same 24 hours in the other.
3. Check units in the column headers: precipitation is mm/h in the hourly file and mm/day in the daily file; pressure is kPa.
4. To confirm a value, open the row's `source_url`. It re-runs the NASA request for that day.
5. Record the parameter names used (T2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN, ...). Definitions: [POWER parameters](https://power.larc.nasa.gov/docs/tutorials/parameters/).

## Limits
POWER values are model and satellite estimates for a grid cell, not readings from a weather station at FRIB.

## References
- [NASA POWER home](https://power.larc.nasa.gov/)
- [POWER API overview](https://power.larc.nasa.gov/docs/services/api/)
