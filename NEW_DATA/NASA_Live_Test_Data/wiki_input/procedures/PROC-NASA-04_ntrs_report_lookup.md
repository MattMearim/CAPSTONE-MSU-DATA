# Radiation test report lookup (NTRS) - NASA-1

TRAINING PROCEDURE - written for testing the FRIB decision-support system with public NASA data. Not a FRIB operating procedure.

Version: NASA-1 (2026-11-17)

## Purpose
Find and cite NASA radiation-effects test reports (single-event effects, total ionizing dose).

## Inputs
- The `NTRS-*.md` records in [documents](../documents/) - e.g. [NTRS-20040171458](../documents/NTRS-20040171458.md) (MSU NSCL test facility).

## Steps
1. Cite the NTRS ID and the record link. Every record has a link of the form https://ntrs.nasa.gov/citations/<ID>.
2. The NTRS ID year is when NTRS added the record, not the publication date. Use the "Published" field for dates.
3. Author names vary between records (e.g. "Campola, Michael" / "Michael J Campola"). Check the "Related records in this set" links at the end of each record.
4. Two records can share a title and still be different tests (e.g. the two HSYE-117RH reports). Compare abstracts before treating them as duplicates.
5. Text is as published by NASA, including typos (e.g. "Vix-11 Pro" for Virtex-II Pro). Do not silently correct it in a citation.

## References
- [NASA Technical Reports Server](https://ntrs.nasa.gov/)
- [Facility for Rare Isotope Beams (successor of NSCL)](https://frib.msu.edu/)
