# NASA public data snapshot - data dictionary

Retrieved 2026-10-30 (approx. 15:40-16:30 America/Detroit) from public NASA web services. All values are as published by NASA; no values were corrected.

## How the column names work in the FRIB app
- A unit in square brackets (`[C]`, `[kPa]`, `[%]`, `[m/s]`) is a unit the FRIB app knows. The app converts these to SI when it imports the file (C -> K, kPa -> Pa, % -> fraction).
- Units the app does not know are written into the column name instead (`velocity_km_per_s`, `distance_au`, `precipitation_mm_per_h`). The app imports these as unitless numbers; the unit is in the name and in this dictionary.
- Every file has a `source_url` column with the NASA link for that row. Long links are stored by the app as text log entries.
- Time axis: `timestamp_utc` (hourly weather, fireballs) and `timestamp_lst` (daily weather). The app stores times without a zone as UTC - the daily file is really local solar time. `time_tdb` in the close-approach file is kept as text because TDB is not UTC and two approaches share the same minute.

## power_frib_hourly.csv
Source: NASA POWER Hourly API v2.10 (power.larc.nasa.gov), community RE, point 42.7245 N, 84.4746 W (Michigan State University / FRIB, East Lansing, Michigan; POWER grid elevation 281.97 m). Time standard: UTC. Period 2026-10-01 00:00 to 2026-10-28 23:00 (672 hourly rows).

| Column | NASA parameter | Unit |
|---|---|---|
| timestamp_utc | hour (UTC) | ISO 8601 |
| air_temperature [C] | T2M, temperature at 2 m | degrees Celsius |
| dew_point [C] | T2MDEW, dew/frost point at 2 m | degrees Celsius |
| relative_humidity [%] | RH2M, relative humidity at 2 m | percent |
| surface_pressure [kPa] | PS, surface pressure | kilopascal |
| wind_speed_10m [m/s] | WS10M, wind speed at 10 m | metres per second |
| wind_direction_10m_deg | WD10M, wind direction at 10 m (from which the wind blows) | degrees |
| precipitation_mm_per_h | PRECTOTCORR, precipitation corrected | millimetres per hour |

## power_frib_daily.csv
Source: NASA POWER Daily API v2.10, same point. Time standard: local solar time (LST), not UTC. Period 2025-10-01 to 2026-10-28 (393 daily rows).

| Column | NASA parameter | Unit |
|---|---|---|
| timestamp_lst | day in local solar time, written as YYYY-MM-DDT00:00:00 (no time zone) | ISO 8601 |
| air_temperature_mean [C] | T2M | degrees Celsius |
| air_temperature_max [C] | T2M_MAX | degrees Celsius |
| air_temperature_min [C] | T2M_MIN | degrees Celsius |
| relative_humidity [%] | RH2M | percent |
| surface_pressure [kPa] | PS | kilopascal |
| wind_speed_10m [m/s] | WS10M | metres per second |
| precipitation_mm_per_day | PRECTOTCORR | millimetres per day |
| solar_irradiance_kWh_per_m2_per_day | ALLSKY_SFC_SW_DWN, all-sky surface shortwave downward irradiance | kilowatt-hours per square metre per day |

NASA POWER fill value: **-999** means the value is not available (for example, recent days whose satellite inputs have not been processed yet).

## jpl_fireballs.csv
Source: NASA/JPL CNEOS Fireball Data API v1.2 (ssd-api.jpl.nasa.gov/fireball.api). Fireballs (bright meteors) detected by U.S. Government sensors, 2024-01-01 to retrieval. 89 rows.

| Column | Meaning | Unit |
|---|---|---|
| timestamp_utc | peak brightness time | ISO 8601 UTC |
| latitude_deg | latitude of peak brightness; negative = south | degrees |
| longitude_deg | longitude of peak brightness; negative = west | degrees |
| altitude_km | altitude above the geoid at peak brightness | kilometres |
| velocity_km_per_s | pre-impact velocity | kilometres per second |
| radiated_energy_1e10J | approximate total optical radiated energy | units of 10^10 joules |
| impact_energy_kt | calculated total impact energy | kilotons of TNT |

Blank cells mean NASA did not publish that value.

## jpl_close_approaches.csv
Source: NASA/JPL SBDB Close-Approach Data API v1.5 (ssd-api.jpl.nasa.gov/cad.api). Near-Earth asteroid close approaches to Earth within 0.02 au, 2026-09-01 to 2026-12-31. 204 rows.

| Column | Meaning | Unit |
|---|---|---|
| time_tdb | time of close approach (text column, not used as the time axis), TDB (Barycentric Dynamical Time, about 69 s ahead of UTC) | ISO 8601 |
| object | asteroid designation | category |
| distance_au | nominal approach distance (rounded to 6 decimals) | astronomical units |
| distance_min_au / distance_max_au | 3-sigma minimum / maximum distance | astronomical units |
| relative_velocity_km_per_s | velocity relative to Earth at close approach (rounded to 3 decimals) | kilometres per second |
| absolute_magnitude_mag | absolute magnitude H (lower = larger object) | magnitudes |
| diameter_km | diameter if known | kilometres |
| time_uncertainty | 3-sigma close-approach time uncertainty, formatted days_hours:minutes | category |
| status | past = before retrieval; predicted = after retrieval | category |

Reference values: 1 au = 149,597,870.7 km; 1 lunar distance (LD) = 384,400 km = 0.002569555 au.

## documents/NTRS-*.md
32 bibliographic records (title, date, type, NASA center, authors, keywords, abstract) from the NASA Technical Reports Server (ntrs.nasa.gov) on radiation effects testing of electronics - single-event effects (SEE) and total ionizing dose (TID) - from 1984 to 2026. Text is as published by NTRS, including NTRS's own typos and formatting.

## Links

### Files in this data set
- [power_frib_hourly.csv](../datasets/power_frib_hourly.csv) - hourly weather at FRIB (UTC)
- [power_frib_daily.csv](../datasets/power_frib_daily.csv) - daily weather at FRIB (local solar time)
- [jpl_fireballs.csv](../datasets/jpl_fireballs.csv) - fireball reports since 2024
- [jpl_close_approaches.csv](../datasets/jpl_close_approaches.csv) - asteroid close approaches Sep-Dec 2026
- Review procedures: [PROC-NASA-01](../procedures/PROC-NASA-01_power_weather_review.md), [PROC-NASA-02](../procedures/PROC-NASA-02_fireball_record_review.md), [PROC-NASA-03](../procedures/PROC-NASA-03_close_approach_review.md), [PROC-NASA-04](../procedures/PROC-NASA-04_ntrs_report_lookup.md), [PROC-NASA-05](../procedures/PROC-NASA-05_unit_conversion_reference.md)

Every CSV row has a `source_url` column that links to the NASA record or API request for that row.

### NASA sources
| Data | Human-readable page | API documentation | Request that produced the file |
|---|---|---|---|
| POWER hourly | [NASA POWER](https://power.larc.nasa.gov/) | [Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/) | [hourly request, 1-28 Oct 2026](https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=T2M,T2MDEW,RH2M,PS,WS10M,WD10M,PRECTOTCORR&community=RE&longitude=-84.4746&latitude=42.7245&start=20261001&end=20261028&format=CSV&time-standard=UTC) |
| POWER daily | [POWER parameter definitions](https://power.larc.nasa.gov/docs/tutorials/parameters/) | [Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) | [daily request, Oct 2025 - Oct 2026](https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M,T2M_MAX,T2M_MIN,RH2M,PS,WS10M,PRECTOTCORR,ALLSKY_SFC_SW_DWN&community=RE&longitude=-84.4746&latitude=42.7245&start=20251001&end=20261028&format=CSV) |
| Fireballs | [CNEOS fireball reports](https://cneos.jpl.nasa.gov/fireballs/) | [Fireball Data API](https://ssd-api.jpl.nasa.gov/doc/fireball.html) | [fireballs since 2024-01-01](https://ssd-api.jpl.nasa.gov/fireball.api?date-min=2024-01-01) |
| Close approaches | [CNEOS close approaches](https://cneos.jpl.nasa.gov/ca/) | [SBDB Close-Approach Data API](https://ssd-api.jpl.nasa.gov/doc/cad.html) | [approaches within 0.02 au, Sep-Dec 2026](https://ssd-api.jpl.nasa.gov/cad.api?date-min=2026-09-01&date-max=2026-12-31&dist-max=0.02&diameter=true) |
| Report records | [NASA Technical Reports Server](https://ntrs.nasa.gov/) | - | one record per file, linked in each `NTRS-*.md` |
