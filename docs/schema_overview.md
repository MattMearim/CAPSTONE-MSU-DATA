# Schema overview (draft v0.1.0)

Status: draft, not yet reviewed by the sponsor.

## Design rules

1. **Three record types, one provenance block.** Time-series, event log,
   document. All three embed `provenance.schema.json`.
2. **No domain-specific fields.** Channel names, units, tag names and
   configuration keys are data, not schema. A new domain needs zero schema
   changes. `tests/test_schemas.py` enforces this.
3. **Provenance is mandatory.** Source, asset, acquisition time and a
   `synthetic` flag are required. Synthetic records must also state the
   generator name, version and seed so they can be regenerated.
4. **Missing data is explicit.** A missing sample is `null`, optionally
   with a per-sample quality flag. Nothing is silently dropped or filled.
5. **Two time bases.** A channel has either `sample_rate_hz` (uniform) or
   `timestamps` (irregular), never both.
6. **Records link through `event_id`.** A waveform capture and the
   interlock log from the same trip share one `event_id`.

## Open questions for the sponsor

- Are per-channel arrays in JSON acceptable, or should large waveforms be
  stored in a binary file (Parquet/HDF5) that the JSON record points to?
- Is the severity list (info, warning, alarm, trip) the right vocabulary?
- Should configuration be free-form, or a list of named settings with units?
- Which timestamp precision is needed (milliseconds, microseconds)?
- How are document revisions identified in the real procedure system?
