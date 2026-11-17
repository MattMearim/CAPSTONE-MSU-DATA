# Asteroid close-approach review (JPL SBDB) - NASA-1

TRAINING PROCEDURE - written for testing the FRIB decision-support system with public NASA data. Not a FRIB operating procedure.

Version: NASA-1 (2026-11-17)

## Purpose
Review asteroid close-approach records and answer distance questions correctly.

## Inputs
- [jpl_close_approaches.csv](../datasets/jpl_close_approaches.csv)
- Definitions: [data_dictionary.md](../documents/data_dictionary.md)

## Steps
1. Times are **TDB**, not UTC (TDB is about 69 s ahead of UTC). State this when quoting a time.
2. Convert distances when asked: 1 au = 149,597,870.7 km; 1 lunar distance (LD) = 384,400 km = 0.002569555 au. Distances are measured from Earth's center.
3. Use `distance_min` / `distance_max` and `time_uncertainty` to judge how certain an approach is.
4. Rows with `status = predicted` are in the future as of retrieval (30 Oct 2026). Do not report them as observed.
5. Lower absolute magnitude (H) means a larger object. Diameters are mostly not given.
6. To look up an object, open its `source_url` ([JPL Small-Body Database lookup](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html)).

## Limits
Future months look almost empty because most small asteroids are discovered only shortly before or after their approach - see the [CNEOS close-approach introduction](https://cneos.jpl.nasa.gov/ca/intro.html).

## References
- [CNEOS close approaches](https://cneos.jpl.nasa.gov/ca/)
- [SBDB Close-Approach Data API](https://ssd-api.jpl.nasa.gov/doc/cad.html)
