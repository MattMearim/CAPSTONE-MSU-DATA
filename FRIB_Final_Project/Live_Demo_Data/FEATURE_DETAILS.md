# Fictional Test Lab

The pack supplies 13 small datasets and seven procedures for exercising all four project levels. Every source is fictional training material. Approved status in these samples is a test choice; these are not facility operating procedures, real measurements, or authorization to operate equipment.

The manifest is `sample_data/test_lab/manifest.json`. It records source checksums, file sizes, explicit import mappings, expected results, suggested questions and presentation steps. Data lives in `sample_data/test_lab`; procedures live in `sample_docs/test_lab`. Browsing or downloading the pack does not save anything to the application.

## Quick verification

Stop a running FRIB launcher with Ctrl+C first so any missing test-runner dependencies can be prepared. From the project directory, double-click **Run Test Lab.cmd**, or use PowerShell. The launcher checks setup and installs missing test-runner requirements automatically:

```powershell
& '.\Start FRIB.cmd' --test-lab --output test_lab_results
```

The runner calls the actual FastAPI application through its test client in a newly created temporary data directory. It forces mock answers, hash embeddings and SQLite, and creates its own temporary configuration so a configured external index cannot be used. It never calls the running server or the reset endpoint, and it restores the caller's environment afterward. Temporary application content is removed at exit. The output directory contains `test-lab-results.json`, `TEST_LAB_RESULTS.md`, and event/preview/analysis/review JSON artifacts. Return code 0 means all grouped checks passed; return code 1 means at least one failed. Read the recorded result for the current count rather than treating this document as execution evidence.

For optional developer checks and fixture generation, copy **Active interpreter** from **System & upgrades → Hardware details** and replace the placeholder below with that exact path. A retained `.venv` may be inactive after an upgrade; refresh the path after further upgrades. Stop FRIB before changing installed packages. From the project folder:

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest tests/test_test_lab.py -q
```

To regenerate fixtures without touching runtime data, use the same active interpreter:

```powershell
& $fribPython scripts/generate_test_lab.py
```

Or generate a separate project-shaped copy with `--output C:\path\to\fixture-copy`; pass that copy's `sample_data\test_lab\manifest.json` to the runner with `--manifest`. The generator uses standard-library code plus optional ReportLab for authoring the PDFs. With the ordinary application dependencies, it copies the shipped, checked PDFs; no new dependency is needed to use the pack. Fixtures and checksums are repeatable with the same PDF library version or the same shipped PDF baseline. Execution times and generated document/draft IDs vary.

## Dataset catalog

| ID / file | What to demonstrate | Expected result |
|---|---|---|
| RF-TRIP / `rf_trip.csv` | RF field, forward/reflected power, pressure and recorded interlock | Reference 0 s; pressure change 100 Pa; approximate field 1/e crossing 25 ms. Domain RF plots and evidence; coincidence does not prove cause. |
| RF-XRAY / `field_emission.csv` | Gradient supplied by a per-row unit column and X-ray counts/s | V/m normalization, descriptive scatter/correlation and scan categories. No physical field-emission diagnosis or safe-gradient claim. |
| CRYO / `cryo_temperature.csv` | Celsius to kelvin, mbar to Pa, missing 12-15 s interval, declared stability and bounds | First temperature 4.15 K; first pressure 100000 Pa. Recording gap and declared differences flagged; generic evidence summary. |
| PLC / `plc_sequence.csv` | Categorical PLC states, boolean permit, pressure and severity-labeled notes | RUNNING -> WARNING -> INTERLOCKED, transitions at 4 and 7 s, 21 logs; categories do not become numeric waveforms. |
| UNITS / `mixed_units.tsv` | Native TSV, ISO datetimes, mV/kV row units, Fahrenheit, kPa/mbar, percent | Voltage `[1,2000,0.5]` V; temperature `[273.15,293.15,373.15]` K; pressure `[1000,2000,1000]` Pa; fraction `[0.25,0.5,1]`. |
| REPAIR / `damaged_capture.csv` | Duplicate row, NA token, invalid numeric cell, malformed row | Raw save blocked. Explicit reviewed-copy repairs retain four numeric values `[1,2,5,7]` V and unrelated text; original bytes and receipt remain available. |
| QUALITY / `gap_jump_flatline.csv` | Missing cadence/channel, abrupt voltage step, constant temperature, declared bounds/stability | L2 gap, missing-channel, out-of-bounds, stability, flatline and baseline-change flags. All valid measured readings remain. |
| BAD-UNIT / `incompatible_units.csv` | Voltage suffix contradicting a pressure header | Blocked with incompatible dimensions and no event writes. |
| DBM / `unsupported_dbm.csv` | Unsupported logarithmic power unit | Blocked; never silently relabeled W or dimensionless. A physically reviewed conversion is needed outside this app. |
| MECHANICAL / `mechanical.json` | Native event, 200 Hz vibration and 20 Hz temperature | Original grids retained; derived alignment, roughly 12 Hz post-event spectrum, higher post-event RMS and K normalization. |
| UNTIMED / `row_order.csv` | RF-labeled evidence without recorded timestamps or required domain channels | Explicit row-order coordinates, descriptive summary, no physical rates/durations/spectrum. |
| LOG / `operator_shift.log` | Four ISO-timestamped narrative lines and explicit `name=value` states | PLC sequence from recorded categorical assignments, four logs and no invented waveforms. |
| PDF-NOTE / `operator_note.pdf` | Selectable-text PDF as evidence | Logs retain source-page metadata. Untimed headings/footer cause explicit row-order fallback. No OCR, PDF table/image interpretation or physical diagnosis. |

## Procedure catalog and revision behavior

| Files | Upload metadata | Test question / purpose |
|---|---|---|
| `rf_trip_rev_a.md`, `rf_trip_rev_b.md` | Same title, versions LAB-A and LAB-B, both approved for the exercise | RF cavity trip reflected power tuner pressure evidence review. Both approved versions may be cited until A is explicitly retired. |
| `rf_trip_draft_c.md` | LAB-C-DRAFT, **unapproved** | Similar content plus a draft-only canary; it must never appear among retrieved source excerpts. |
| `rf_xray_scan.md` | LAB-1, approved | RF X-ray gradient scan conditioning descriptive evidence limitations. |
| `plc_sequence.md` | LAB-1, approved | PLC RUNNING WARNING INTERLOCKED sequence permit log evidence review. |
| `mechanical_vibration.txt` | LAB-1, approved | Mechanical vibration bearing temperature spectrum RMS evidence review. |
| `cryo_review.pdf` | LAB-1, approved | Cryogenic helium temperature pressure capture gap evidence review; page 1 citation and exact original download. |

Approval and version are source metadata. The current application does not automatically supersede an older approved revision or validate facility signatures. The runner proves coexistence of A/B, exclusion of draft C, explicit deletion of A from retrieval/downloads, and no resurrection after restart.

## Manual full-system walkthrough

1. Open **Test Lab**, choose a scenario and review its expected outcome. Download source files if using the general upload screens. Import approved procedures with their supplied title/version; leave draft C unapproved. Procedure uploads are always explicit.
2. Preview **RF-TRIP** with the manifest mapping. Confirm four measurement channels, canonical units and `RF_INTERLOCK` as a category. Save explicitly, open the event and run analysis. Inspect waveforms, pressure/power evidence, decay-method limitation and the recorded reference time.
3. Ask the supplied RF question with the event selected. Compare measured findings with cited procedure excerpts, version labels and source downloads. In mock mode the response is extractive, without AI interpretation. Create a draft; confirm approved knowledge is still absent until review. Approve it as a named fictional reviewer.
4. Try **PLC** and **LOG**. Confirm recorded states/booleans and text severity remain distinct. Correct the PLC draft's summary while retaining observations, then save named review. Escalate the log or X-ray draft; confirm escalation creates no approved knowledge.
5. Preview **CRYO**, **QUALITY** and **UNITS**. Inspect normalization, recorded gaps and the exact declared expectations in the manifest. Numeric limits use stored units (K, Pa, V). A temperature stability tolerance is a temperature difference; do not add 273.15 to a tolerance. A flagged pattern does not prove instrument failure or negligence.
6. Preview **REPAIR** before selecting any repair. It must be blocked. Choose duplicate removal, missing-token marking for `voltage [V]`, invalid numeric cell at physical source row **6**, and malformed row **8** explicitly. Re-preview and check the receipt and retained text. Save the reviewed copy; download both original and reviewed copy. No fill/interpolation operation exists. The manifest keeps repairs in `expected.repair_options`, never selected by default in `options`.
7. Try **BAD-UNIT** and **DBM**; neither should save. Try **UNTIMED** and **PDF-NOTE**; their explicit fallback must avoid invented timing or domain physics.
8. Use the dataset/procedure file lists to add, download and remove a supporting file. Retire RF revision A explicitly. Restart and verify stored evidence/analyses/knowledge and revision B remain. Delete a test event only when ready to remove its associated originals, analysis, drafts, reviews and knowledge.

Sample event IDs are stable (`LAB-...`). Reusing the same ID is rejected to preserve prior evidence. For repeated manual trials, use a new ID or explicitly delete the previous fictional event. The isolated runner always starts empty and needs no reset.

## API mapping and evidence

Dataset `import_kind=mixed` or `text` uses `/ingestion/preview` (multipart `file`, JSON form field `options`, `validate=true`), followed only on user action by `/ingestion/import`. Native `event` JSON uses `POST /events`, then its unchanged source bytes can be attached through `/events/{id}/files`. Procedure entries use `/documents/index` with `approved`, `title` and `version` form fields. The manifest's `options` are ready for these calls, including quality expectations. All file paths are project-relative; the UI/runner must keep them inside the pack root.

The runner checks 32 grouped outcomes: fresh insufficient-context behavior; seven procedure original/index/approval/version lifecycles; thirteen dataset quality/import/unit/analysis/original/export outcomes; approved-only retrieval and cross-format citations; five human approval/correction/escalation outcomes; revision retirement; attachment operations; persistent restart; and dependent event deletion. A grouped check contains multiple assertions and is not a unit-test count or code-coverage percentage. Pytest additionally verifies reproducible bytes, manifest integrity, genuine selectable PDFs, distinct native sampling grids, isolation/environment restoration and truthful failure when a fixture is changed.

The pack validates implemented behavior, not real-world engineering accuracy. It does not connect to EPICS/FRIB, test live controls, validate causal diagnosis, demonstrate trained prediction, test local AI providers, perform OCR, authorize machine commands or certify operating procedures. Cryogenic evidence is handled by the generic descriptive processor because a dedicated cryogenic physics model is not implemented.
