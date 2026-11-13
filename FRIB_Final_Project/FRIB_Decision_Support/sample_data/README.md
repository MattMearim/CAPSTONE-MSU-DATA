# Ready-to-import demonstration datasets

These datasets are synthetic, with reproducible seed 42, and are not FRIB operational evidence.

- `rf_demo.json` / `rf_demo.csv`: cavity field, forward/reflected power and tuner pressure around an RF trip.
- `mechanical_demo.json` / `mechanical_demo.csv`: vibration and bearing-temperature trends around a synthetic anomaly.
- `plc_demo.json` / `plc_demo.csv`: process signal and, in JSON, PLC state/log chronology.
- `mixed_units_and_states.csv`: mixed-unit pressure/temperature, PLC categories, booleans and operator notes; use the mixed CSV importer with its detected column roles and units.
- `operator_shift.log`: timestamped fictional notes with severity labels and explicit state assignments; use the text/PDF evidence importer.

For a complete demonstration, import the JSON in **Create Dataset -> Import JSON dataset**. JSON preserves metadata, state events, logs and provenance. Each example has a stable DEMO identifier; importing the same example twice is rejected to protect the first copy.

The CSV files are wide numeric tables for the interactive importer. Map `time_s` to the time column and signal headers to their corresponding signal names. CSV does not include the JSON's state/log metadata, so inferred event reference times may differ. Original uploaded bytes are preserved separately as evidence.

The reference procedures in `sample_docs` are fictional. They should be explicitly marked as approved only in a demonstration workspace.
# Quality review exercise

`quality_review.csv` deliberately contains duplicate, missing and invalid entries, mixed declared pressure scales, a recording gap, a sudden pressure change and constant temperature. Use it with `docs/DATA_QUALITY_GUIDE.md` to exercise explicit repairs and expectation checks.

