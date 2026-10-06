# Public MSU data sources

Surveyed 2026-10-06. Purpose: an out-of-domain validation set. The core
system is built against synthetic RF, mechanical and PLC data. Feeding it
real data from an unrelated field tests the claim that it is field-agnostic.

Nothing has been downloaded yet.

## Summary

| Source | Run by MSU? | Resolution | Channels | Access | Reuse terms | Verdict |
|---|---|---|---|---|---|---|
| KBS LTER weather station | Yes | Hourly and daily | ~10 | Direct CSV, no login | Publication needs written permission | Best first pick |
| AmeriFlux KBS towers | Yes (MSU PIs) | Half-hourly | Many | Free account | CC-BY-4.0 | Best license |
| Enviroweather | Yes | Sub-hourly to daily | Many, 81 stations | Website only | Not confirmed | Ask first |
| Campus energy and utilities | Yes | Annual | Few | PDF reports | n/a | Not usable |

## 1. KBS LTER weather station

Kellogg Biological Station is an MSU research station. Its long-term
ecological research program publishes weather data.

- Hourly table: <https://lter.kbs.msu.edu/datatables/13>,
  CSV at <https://lter.kbs.msu.edu/datatables/13.csv>.
  November 1992 to December 2021.
- Daily table: <https://lter.kbs.msu.edu/datatables/12>,
  CSV at <https://lter.kbs.msu.edu/datatables/12.csv>.
  1988 to 2025, 23 variables with quality flags.
- Hourly columns: UTC datetime, PAR, solar radiation, wind speed, wind
  direction, relative humidity, absolute humidity, air temperature,
  barometric pressure, rainfall.
- Why it is useful: 30 years of real sensor data with gaps, sensor
  changes, and a documented caveat that the rain gauge is unreliable
  below freezing. That exercises missing-data handling and quality flags.
- Terms: "Data in the KBS LTER core database may not be published without
  written permission of the lead investigator or project director."
  Publications must acknowledge KBS LTER support.
  <https://lter.kbs.msu.edu/data/terms-of-use/>
- What that means here: fine to download and test with locally. Do not
  commit the data to this repo. Before putting plots or values in the
  final report or presentation, email lter.data.manager@kbs.msu.edu.
- Not confirmed: the license text on the archived copy
  (doi.org/10.6073/pasta/4c30523bae14c4340e4d9c90e72f90c4). The page could
  not be read during the survey. It may carry a more open license.

## 2. AmeriFlux towers at KBS

Instrument towers measuring gas and energy exchange over farm fields,
run by MSU investigators.

- Example site US-KM1: <https://ameriflux.lbl.gov/sites/siteinfo/US-KM1>.
  Sister sites include US-KL1 and US-MWF.
- Half-hourly data, 2009 to 2021 available, many simultaneous channels.
- License: CC-BY-4.0. Reuse and redistribution are allowed with citation.
- Citation for US-KM1: G. Philip Robertson, Jiquan Chen (2022), AmeriFlux
  BASE US-KM1 KBS Marshall Farms Corn, Ver. 4-5,
  <https://doi.org/10.17190/AMF/1647439>
- Access: free AmeriFlux account, and a short form stating intended use.
  A team member has to do this step by hand.
- Why it is useful: the cleanest license, and many channels recorded
  together, which tests alignment across channels.

## 3. MSU Enviroweather

A network of 81 weather stations across Michigan, including one on
campus (East Lansing / MSUHORT).

- <https://enviroweather.msu.edu/>, station page
  <https://enviroweather.msu.edu/stations/msu>
- Not confirmed: download format, time resolution and terms of use. The
  site only loads in a browser and its sister site blocks automated
  readers. Check the station page by hand for a download option, and
  contact Enviroweather before reusing data.

## 4. Campus energy and utilities

MSU Infrastructure Planning and Facilities publishes annual utility
statistics and planning reports
(<https://ipf.msu.edu/environment/energy/energy-generation>). No public
time-series data or dashboard was found. Not usable for this project
unless IPF provides data on request.

## 5. MSU engineering research data

No public College of Engineering repository of equipment or sensor
datasets was found. MSU Libraries provides researchers access to Dryad,
so individual MSU datasets may exist there, but none relevant turned up.
The engineering librarian is the next step if a true engineering dataset
from MSU is wanted.

## Recommendation

1. Start with the KBS hourly weather CSV. It needs no account and is the
   fastest way to prove the ingestion contract accepts foreign data.
2. Add one AmeriFlux site for anything that will appear in the final
   report, because its license clearly allows it.
3. Treat these as a fourth, out-of-domain test. They do not replace the
   three required engineering domains.
