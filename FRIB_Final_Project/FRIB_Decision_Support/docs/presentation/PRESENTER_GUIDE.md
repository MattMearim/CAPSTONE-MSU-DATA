# L1/L2 presenter guide

Use the 12–15 minute sequence for the live presentation. Use the evidence appendix to demonstrate the remaining features without trying to run every edge case on stage. All example captures and procedures are fictional; synthetic timing and frequency checks demonstrate software behavior, not FRIB fault-diagnosis accuracy.

## Prepare once

The delivered evidence is under:

```text
C:\Users\berda\OneDrive\Documents\FRIB\deliverables\L1_L2_Presentation\
  Feature_Showcase.html
  evidence\scenario_results.json
  evidence\pytest-results.xml
  evidence\cases\<scenario-id>.json
  evidence\demo_inputs\<source-file>
  evidence\artifacts\<scenario-id>-event.json
  evidence\artifacts\<scenario-id>-analysis.json
```

Not every scenario creates an event or analysis artifact: rejected inputs should not produce stored evidence. Open `Feature_Showcase.html` before presenting. Its expected/observed checks, plots and test results work offline. Keep the entire presentation folder together so source-download links work. The showcase embeds display data; the adjacent JSON/XML records are the underlying evidence.

Run the application from the project root in PowerShell. A separate presentation data directory keeps demonstrations away from existing captures:

```powershell
$env:FRIB_DATA_DIR = Join-Path (Get-Location) 'presentation_live_data'
$env:FRIB_LLM_PROVIDER = 'mock'
$env:FRIB_EMBEDDING_PROVIDER = 'hash'
$env:FRIB_VECTOR_PROVIDER = 'sqlite'
& '.\Start FRIB.cmd' --check
& '.\Start FRIB.cmd'
```

Open `http://127.0.0.1:8501`; the API documentation is `http://127.0.0.1:8000/docs`. Keep the launcher terminal open; Ctrl+C stops its services. If the normal ports are occupied, use `& '.\Start FRIB.cmd' --api-port 8002 --port 8502`. On a fresh extraction, double-click `Start FRIB.cmd`; first setup needs internet access and downloads a verified private Python when no supported runtime is available. The installed deterministic L1/L2 workflow needs no network or model download.

Have these project files ready in the file picker:

- `sample_data/quality_review.csv` — deliberate duplicate, invalid and missing measurements, mixed pressure scales, gaps, a step and constant temperature.
- `sample_data/mixed_units_and_states.csv` — per-row pressure units, mixed temperature scales, PLC states, booleans and operator notes.
- `sample_data/operator_shift.log` — timestamped log evidence and explicit state assignments.
- `sample_data/rf_demo.json`, `mechanical_demo.json`, `plc_demo.json` — complete reproducible domain captures with metadata, states and logs.

Import JSON examples only once per presentation data directory. Their fixed IDs intentionally reject duplicate imports; selecting an existing example is sufficient for a repeated presentation. Do not delete real captures to make a demonstration repeatable.

## Core live sequence: 14 minutes

### 0:00–1:00 — Establish scope and the evidence record

In `Feature_Showcase.html`, choose **Start presentation**. Show **The evidence** and **The operating model**. Arrow keys navigate; Space reveals the next item in presentation mode; Escape exits.

Say: “Level 1 preserves what was recorded. Level 2 turns that evidence into checked engineering views. The source, an explicitly reviewed copy, and a derived result remain traceable. A quality flag is a review question, not a diagnosis.”

Point to the independently calculated scenario and JUnit counts. Whole-project tests include L3/L4; the named L1/L2-related module subset is narrower. A scenario count is a count of recorded demonstrations, not a test count. Open one scenario's expected/observed checks if asked for proof.

### 1:00–5:00 — Review and explicitly repair a source

Open **Create Dataset → Import CSV / mixed data**, choose `sample_data/quality_review.csv`, and name the dataset `Live quality review`. Keep the domain **General evidence**.

1. Expand **Level 1 · Original file quality**. Show source rows and total affected counts. The source contains one redundant row at physical line 6, `NA` at line 4, and `broken` at lines 5–6. Unit scales are compatible and remain visible. No repair is selected automatically.
2. Under **Optional repairs · your choice**, choose **Remove redundant exact duplicate rows**, **Mark recognized missing-value tokens as empty**, and **Mark selected invalid measurements as empty** for `pressure [kPa]`. For the invalid-cell selection, use original source row **5**: line 6 is already excluded as the redundant row. Do not choose the skip-invalid checkbox for this exercise.
3. In **What each column means**, confirm `pressure [kPa]` and `temperature [C]` are **Measurement**, `mode` is **Category / state**, and `operator_note` is **Text / log message**. Keep channel names `pressure` and `temperature`. Choose the measured `time [s]` time column and **Seconds (s)**.
4. Open **Optional quality expectations**. Enable **Check expected sampling interval**, enter **1** second, and select pressure for declared rules. Enable **Expected to remain stable · pressure**, enter absolute tolerance **100 Pa**, and set minimum **0 Pa**, maximum **1500 Pa**. These are deliberate demonstration expectations, not facility operating limits. Temperature can use **Check repeated identical samples · temperature**, count **5**.
5. In **Ready-to-save preview**, compare **Level 1 · Original file quality** with **Level 1 · Import-copy quality**, **Level 2 · Signal quality and expectations**, and **Selected repair receipt**. The receipt should show one duplicate row removed, one recognized token blanked and one invalid cell blanked; input/output records are 11/10. The original source remains unchanged.
6. Click **📥 Import dataset** once the validated preview is ready. There should be 8 pressure measurements in Pa, 10 temperature measurements in K, 2 mode-state records (initial READY, then RUN) and 10 logs. Temperature is 293.15 K. Pressure has four initial observations at 1000 Pa and four later observations at 20000 Pa; the absent observations remain absent.

Say: “The reviewed copy contains no invented values. Pressure now has fewer observed samples than temperature. The declared one-second schedule makes the long intervals reviewable, and the declared stability tolerance makes the recorded change reviewable.”

### 5:00–7:00 — Inspect L2 findings and trace the originals

In **Investigate Event → 1 · Evidence**, show the pressure plot, its line breaks and independent unit axes. Expected findings include `BLANK_VALUES_SKIPPED`, pressure `OUT_OF_BOUNDS`, `STABILITY_EXCEEDED`, `BASELINE_CHANGE`, `RECORDING_GAP`, `IRREGULAR_CADENCE`, and a temperature `FLATLINE_RUN` and `RECORDING_GAP`. Counts describe this configured example; a flatline does not identify a stuck sensor.

Open **Capture quality and operator expectations**. Use **Check saved event quality**, filter the report by severity or channel, and show **Download quality report (JSON)**. This recomputation does not rewrite saved observations.

Open **Prepare original and standardized exports** to show **Original event JSON**, **Standardized JSON** and **Standardized CSV**. In the evidence-files area choose `quality_review.csv`, **Prepare evidence download**, and **Download original evidence**. Also show `reviewed_copy.csv`. The unchanged source is the attachment; after repair, original event JSON is the parsed reviewed view before SI conversion.

In **2 · Analysis**, click **▶ Run analysis**. This capture uses a descriptive evidence summary; irregular timing must not silently become an FFT or an interpolated domain duration estimate.

Say: “L1 source locations are physical lines. L2 locations are accepted sample positions and timestamps. They answer different questions. A plotted break marks an interval; it does not reconstruct a missing waveform.”

### 7:00–9:00 — Mixed units, categories and text

Return to **Create Dataset → Import CSV / mixed data** and choose `sample_data/mixed_units_and_states.csv`. Confirm time `time_ms`, **Milliseconds (ms)**, pressure **Per-row unit column** `pressure_unit`, and the helper `pressure_unit` role **Ignore**. Keep `PLC_STATE` spelled exactly as shown. Confirm `enabled` is a category and `operator_note` a log.

Show the validated preview: timestamps are 0, 0.5, 1, 1.5 and 2 seconds; pressure is 1000, 1000, 1050, 1080 and 1020 Pa. Temperature cells in C, F and K share stored K units. PLC/boolean categories and severity-labeled notes remain separate from measurements. Changing a display label does not change the channel identity.

Switch to **Import text / PDF**, choose `sample_data/operator_shift.log`, and show **Extracted source text**, category timeline and severity counts. No numeric channel needs to be invented for text-only evidence. Explain that a selectable-text PDF uses the same evidence path with page/line provenance; a scanned page needs OCR outside this implementation.

Say: “Units come from declarations or a human-confirmed mapping. A pressure name can suggest possible units; it cannot choose Pa or kPa. Text counts and quoted excerpts remain source evidence.”

### 9:00–12:00 — Domain processing on complete synthetic captures

Use **Create Dataset → 📦 Import event JSON** for `sample_data/rf_demo.json`, then **Investigate Event → 2 · Analysis → ▶ Run analysis**. Show measured features and full/pre/post plots: interlock-relative reference, cavity-field decay threshold measure, reflected peak, tuner-pressure pre/post summaries, optional forward/reflected comparison and pretrip spectrum. JSON preserves states/logs that a numeric CSV lacks.

For mechanical and PLC, use the showcase's recorded analysis plots or import `mechanical_demo.json` and `plc_demo.json` if time permits. Mechanical displays vibration RMS and dominant spectral frequency with optional temperature overlay. PLC displays chronological state sequence, transition intervals and sequence warnings. The appendix covers x-ray/gradient standalone and optional RF trends.

Say: “These checks use timestamps and the actual channel bandwidth. Alignment uses the shared recorded interval. FFT amplitudes and frequencies have declared scaling. A correlation, a threshold crossing or a synthetic frequency match does not establish a physical cause.”

### 12:00–14:00 — Demonstrate breadth and close on practical limits

Return to **Feature_Showcase → Feature coverage**. Search `repair`, `unit`, `gap`, `FFT`, and a specific issue code. Open **Complete recorded feature matrix** and **Automated verification**. Show one rejection case alongside one successful case; failed inputs must not appear as stored captures.

Open **Settings → Convert a measurement unit**: choose absolute temperature and convert **68 F → C**, which should be **20 C**. Explain that a temperature difference has separate delta units and no absolute offset. Demonstrate another family only if requested.

Say: “The project runs locally, preserves original evidence, makes repairs explicit, checks the full accepted capture, and derives reviewable views. Real FRIB connectors, approved operational data, calibration and causal validation remain integration and commissioning work.”

If asked about L3/L4, show their position in the architecture and state that their retrieval and human-review tests are in the full suite; this walkthrough is scoped to L1/L2. No model is required for these deterministic checks.

## Evidence appendix: demonstrate every feature group

Use [FEATURE_COVERAGE.md](FEATURE_COVERAGE.md) as the exhaustive test-function index. Its issue-code inventories include limitations where a specific branch lacks a dedicated pytest assertion. Use the scenario manifest for executable demonstrations and the JUnit report for independently collected automated assertions. Do not infer a pass from a feature's existence in source.

| Feature group | Demonstration / place to show it |
|---|---|
| Launch and installation | `start.py --check`; normal/alternate ports; extracted distribution workflow test. First install dependency access is separate from offline use. |
| Three generators | UI generator controls or `scripts/generate_event.py`; fixed seed/custom overrides; bounds and parameter rejection scenarios. Ground truth is only validation metadata. |
| Structured event contract | Native JSON artifact; finite/rate/order/duplicate-name/safe-ID rejection tests. |
| File format handling | Runner UTF-8/BOM/delimiter/quoted record inputs; JSON; TXT/MD/LOG; generated selectable-text/blank PDF inputs. Show byte/page/row/cell/record limits as rejection evidence, not manual giant uploads. |
| Every CSV role and mapping | Mixed sample: numeric/category/log/ignore, renaming, header/suffix/per-row units. Invalid role/mapping settings must reject with no stored event. |
| Every time mode | Runner s/ms/us/ns/min/h/datetime/row-order cases; sparse blanks keep channel-native times; reversals and conflicting ties remain visible. |
| Unit families and ambiguity | Catalog, converter and units scenarios cover time, frequency, voltage, gradient, power, pressure, length, acceleration, velocity, absolute/difference temperature, dimensionless and count rate. Show mV/MV case sensitivity, incompatible dimensions, overflow and unsupported dBm rejection. Name hints remain unassigned. |
| All L1 detectors | Manifest feature search and L1 report JSON; see the complete lowercase issue-code inventory in FEATURE_COVERAGE. Inspect multiple defects from one raw input rather than only a first parse error. |
| All five explicit repairs | Core shows duplicate/token/invalid cell; runner adds stable time sorting and explicitly selected malformed-row exclusion. Receipts identify original source rows/checksums; unsupported/ambiguous repairs and timestamp/unit deletion fail. |
| Original and derived evidence | Original attachment download, reviewed_copy.csv, parsed original JSON, SI JSON/CSV, attachment list/checksums and repair receipt. Add one evidence file, download it, then explicitly delete only that demonstration attachment. |
| Duplicate-ID/persistence/deletion | API lifecycle scenarios/tests; duplicate capture conflict preserves first bytes; restart retains records; dataset deletion removes dependent derived data. Use only isolated demonstration storage. |
| Reference library | Files & Documents upload/download/delete and explicit approval metadata; unapproved files stay outside retrieval. This is file management evidence, not L3 answer-quality proof. |
| All L2 quality codes | Runner controlled waveforms/report JSON plus uppercase issue inventory: required channels, bounds/stability, flatline, spike/step/boundary, duplicate channels, gaps/cadence/rate/coverage, chatter, unit/contract/overflow limits and ordinal timing. |
| Expectations and whole-file assessment | Global/per-channel cadence, limits, required names, stable tolerance and repeated-value count; invalid settings reject; >1,000-point input checks full file before sampled display. |
| Mathematical helpers | Runner cleaning/alignment/FFT/RMS artifacts. Cleaning sort/duplicate averaging is an adapter helper, not an automatic import repair. Downsampling has no anti-alias filter and warns accordingly. |
| Domain processing | RF timing/pressure/decay/power/native FFT; x-ray/gradient descriptive trends; mechanical pre/post RMS/frequency/temperature; PLC chronology/repeated transitions/expected sequence/incomplete context. |
| Fallbacks | Text-only, unknown/missing domain channels, row-order data, gaps/irregularity and numerical-range cases. Show descriptive evidence instead of unavailable domain estimates. |
| Plot/UI behavior | Filter channels/states/severity, time window, title/display labels, normalized view and independent units; report example bounds versus all actual plot gaps; sampled preview markers; row-order axis. These are AppTest/helper assertions unless visually observed in the live session. |

## Repeatable commands and API alternatives

Copy **Active interpreter** from **System & upgrades → Hardware details**, then stop FRIB before installing development packages. From the project root, replace the placeholder with that exact path and create a new evidence directory to regenerate the proof without using live data. A retained `.venv` may be inactive after an upgrade; refresh this path after further upgrades.

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest --junitxml=presentation_evidence\pytest-results.xml -q
& $fribPython scripts/run_l1_l2_demo.py --output presentation_evidence
& $fribPython scripts/build_l1_l2_showcase.py --evidence presentation_evidence --junit presentation_evidence\pytest-results.xml --output presentation_evidence\Feature_Showcase.html
```

The runner's output and exit status must be checked. Keep previous evidence runs rather than replacing their records. The full suite includes L3/L4 and project-distribution tests; the showcase identifies the L1/L2-related subset by explicit test-module names.

Generate one independent JSON capture without the API or AI:

```powershell
& $fribPython scripts/generate_event.py rf --seed 42 --output presentation_rf.json
```

The output file must not already exist. Use another filename for another capture. The generator does not overwrite evidence.

The API's `/docs` page supplies request schemas and Try it out. These PowerShell examples show the deterministic endpoints directly:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/units
Invoke-RestMethod http://127.0.0.1:8000/units/convert -Method Post -ContentType 'application/json' -Body '{"value":68,"from_unit":"F","to_unit":"C"}'
curl.exe -sS -F 'file=@sample_data/mixed_units_and_states.csv' http://127.0.0.1:8000/ingestion/quality
curl.exe -sS -F 'file=@sample_data/mixed_units_and_states.csv' -F 'validate=true' http://127.0.0.1:8000/ingestion/preview
```

`/ingestion/quality` is read-only; `/ingestion/preview` validates without storage. For a complete mapped preview/import, send multipart form `options` as a JSON object using the same fields shown by the UI: time_column/time_unit, column_roles, signal_names, source_units, unit_columns, invalid_rows, quality_expectations and selected `_repairs`. Use `/docs` or the runner's recorded steps to avoid shell-quoting JSON ambiguity. `/ingestion/import` stores only after whole-file validation and retains exact original bytes.

For a saved demonstration event, replace the ID with the actual imported event ID:

```powershell
$demoEventId = 'YOUR_IMPORTED_EVENT_ID'
Invoke-RestMethod "http://127.0.0.1:8000/events/$demoEventId/quality" -Method Post -ContentType 'application/json' -Body '{"expectations":{"expected_interval_s":1}}'
Invoke-RestMethod "http://127.0.0.1:8000/events/$demoEventId/analyze" -Method Post -ContentType 'application/json' -Body '{"expectations":{"expected_interval_s":1}}'
Invoke-RestMethod "http://127.0.0.1:8000/events/$demoEventId/files"
```

Quality recomputation is read-only. Analysis stores a derived result. Deletion requires an explicit demonstration cleanup choice; do not include it in a read-only diagnostic script.

## If the live application is unavailable

Open `Feature_Showcase.html`, then use the same presentation sequence. Show the actual expected/observed scenario checks, native event/analysis plots, quality-report examples and full-suite JUnit test names. Download or open a source input and compare it with its receipt and event artifact. Explain that this is recorded execution evidence, not a newly observed browser run.

If the runner or JUnit source is absent, the showcase displays unavailable evidence rather than assuming success. If any scenario/test failed, retain and explain that result; fix and rerun before claiming a complete passing demonstration. The application can preserve screenshots but does not extract their measurements; live EPICS/FRIB feeds, OCR, causal validation and calibrated operating limits are outside this presentation's implementation evidence.


## Recorded demonstration crosswalk

The delivered runner completed **49 of 49 scenarios**. Open the corresponding scenario in the showcase to show its expected/observed checks, inputs and native outputs. All five repairs and the L1/L2 issue inventories have recorded examples. The full JUnit report includes all four levels and remains a separate result.

| Presentation topic | Recorded case IDs |
|---|---|
| Formats, mappings and schema | L1-01–L1-05, FORMAT-01 |
| L1 detector inventory and unit suggestions | L1-06–L1-10 |
| Repairs and rejected repair guesses | L1-11–L1-13 |
| Limits, skip settings and whole-file preview | L1-14–L1-16 |
| File lifecycle, provenance and deletion | L1-17–L1-18 |
| Unit families, rejection rules and legacy provenance | UNITS-01–UNITS-03 |
| Every L2 issue group and expectation settings | L2-01–L2-17 |
| RF and X-ray/gradient trends | ANALYSIS-01–ANALYSIS-02 |
| Mechanical spectrum and PLC sequence | ANALYSIS-03–ANALYSIS-04 |
| Alignment and adapter cleaning | ANALYSIS-05–ANALYSIS-06 |
| Timing gates and numerical overflow fallback | ANALYSIS-07–ANALYSIS-08 |
| Generator reproducibility, context and validation bounds | GEN-01–GEN-02 |

The slide deck has a separate recorded plotting example in `evidence/slide_evidence/` and `evidence/slide_plot_data.json`. It uses the project quality-review CSV and seeded domain generators. Its assertion receipt is `evidence/slide_evidence/CHECKS.json`. These chart checks are additional evidence and are not added to either the scenario count or the pytest total.
