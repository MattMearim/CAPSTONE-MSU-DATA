# Dosimetry record review - VNPS-1

FICTIONAL TRAINING PROCEDURE - written for testing the FRIB decision-support system with the fictional Vereskovo NPS records. Not a real or FRIB operating procedure.

Version: VNPS-1 (2026-11-17)

## Purpose
Review dose-rate readings and avoid under-reading caused by instrument limits.

## Steps
1. Identify the instrument for every reading and its range: [DOC-1985-0007 - Dosimetry service: inventory of radiation monitoring instruments (extract)](../corpus/DOC-1985-0007_dosimeter-inventory.md). RKS-4 meters stop at 4 R/h; VR-1000 at 1,000 R/h (passport).
2. A reading at the top of the scale (e.g. 4.0 R/h, "off scale", "> scale") is a minimum, not a measurement: [DOC-1986-0028 - Dosimetry service field readings, night of 17 May 1986](../corpus/DOC-1986-0028_dosimetry-night-0517.csv).
3. Check units in the column header before comparing files: R/h in [DOC-1986-0028 - Dosimetry service field readings, night of 17 May 1986](../corpus/DOC-1986-0028_dosimetry-night-0517.csv), mR/h in [DOC-1986-0052 - Gamma dose rate in Vereskovsk and nearby points, 17-20 May 1986](../corpus/DOC-1986-0052_town-doserate-0517-0520.csv), micro-roentgen per second in [DOC-1986-0024 - Telegram No. 1: report of the director to Goskomatom](../corpus/DOC-1986-0024_telegram-0345.md).
4. Check who signed: "V. Morozov" can be the station dosimetry head or the Army major - compare [DOC-1986-0018 - Dosimetry service: report on the radiation situation as of 08:00, 17 May 1986](../corpus/DOC-1986-0018_dosimetry-report-0517.md) and [DOC-1986-0039 - Radiation reconnaissance report, 18 May 1986, 18:00](../corpus/DOC-1986-0039_recon-0518.md).
5. For conversions use [PROC-VNPS-05](PROC-VNPS-05_radiation_units_reference.md).

## References
- [CDC - How to measure radiation and radioactivity](https://www.cdc.gov/radiation-health/about/how-to-measure-radiation.html)
