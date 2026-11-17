# Fireball record review (CNEOS) - NASA-1

TRAINING PROCEDURE - written for testing the FRIB decision-support system with public NASA data. Not a FRIB operating procedure.

Version: NASA-1 (2026-11-17)

## Purpose
Review fireball (bright meteor) records before using them in an analysis.

## Inputs
- [jpl_fireballs.csv](../datasets/jpl_fireballs.csv)
- Definitions: [data_dictionary.md](../documents/data_dictionary.md)

## Steps
1. Treat blank cells as "not published by NASA". Do not fill them. About a third of the records have no velocity.
2. Latitude and longitude are signed: negative latitude = south, negative longitude = west.
3. Energy units differ: radiated energy is in units of 10^10 J; impact energy is in kilotons of TNT (kt). Do not add the two columns together.
4. To confirm a record, open its `source_url` (the Fireball API query for that date) or the [CNEOS fireball page](https://cneos.jpl.nasa.gov/fireballs/).
5. Field definitions are in the [Fireball Data API documentation](https://ssd-api.jpl.nasa.gov/doc/fireball.html).

## Limits
The list contains only events detected by U.S. Government sensors; it is not a complete count of all fireballs.

## References
- [CNEOS fireball and bolide reports](https://cneos.jpl.nasa.gov/fireballs/)
- [Fireball Data API](https://ssd-api.jpl.nasa.gov/doc/fireball.html)
