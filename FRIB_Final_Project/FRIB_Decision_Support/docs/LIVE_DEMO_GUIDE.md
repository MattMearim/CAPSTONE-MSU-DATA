# FRIB live demo: files to evidence to reviewed knowledge

All supplied datasets and procedures are **fictional training material**. They are not FRIB measurements, facility-approved procedures or instructions to operate equipment. Checking an approval box below is an exercise within a disposable demo workspace.

Allow first-time installation to finish before the audience arrives. The live walkthrough takes approximately 15 minutes after startup. The presentation uses real **Ollama qwen3:8b** generation, **all-MiniLM-L6-v2** semantic embeddings and SQLite persistence. On macOS, just double-click **START_LIVE_DEMO.command**; it automatically prepares missing dependencies and models before opening the app. First setup needs internet and several gigabytes of disk space. The dataset is fictional; the assistant is a real local model and its answers still require source review.

## Start and prepare

1. Extract the entire final ZIP. Inside `FRIB_Final_Project`, keep `FRIB_Decision_Support`, `Live_Demo_Data` and the root launcher files together.
2. Stop any currently running FRIB launcher with Ctrl+C, then double-click **START_LIVE_DEMO.command** on macOS or **START_LIVE_DEMO.cmd** on Windows. It checks Python, prepares missing packages and models, starts the services and opens the dashboard with a separate **Demo_Workspace_AI** and real Ollama/sentence-transformers/SQLite providers. The initial setup needs internet; leave the launcher window open while presenting. The normal **START_FRIB.cmd** entry point uses the normal application workspace. Both use the same local ports, so stop one launcher before switching to the other.
3. Open **System & upgrades**. Show the machine information and required software inventory. Checking for newer versions is optional. Queue actual upgrades after the presentation, then stop and restart the launcher to apply them.
4. The demo launcher starts without automatically importing anything. Uploads, saved examples and review decisions are real writes to **Demo_Workspace_AI** and remain for your next demo session. Merely browsing or previewing a **Test Lab** example does not save anything. Use a fresh extracted copy when you want a completely clean rehearsal without deleting previous demo progress.

The sidebar labels used in this guide are **Overview**, **Data workspace**, **Investigation**, **Procedures**, **Assistant**, **Human review**, **Knowledge library**, **Test Lab**, **System & upgrades**, **Settings** and **Help & guidance**.

The separate `Live_Demo_Data` folder supplies **datasets/** (13 files), **procedures/** (seven files), `import_options/<ID>.json` and `configuration/test_lab/manifest.json`. The manifest records expected outcomes and original-file SHA-256 checksums. **Uploading a dataset does not automatically load its companion JSON or the manifest.** Those references tell you how to set the mapping and optional expectations manually. The built-in **Test Lab** is the easiest route when you want the exact supplied presets applied automatically. The optional `FEATURE_DETAILS.md` technical guide uses the application's internal `sample_data/test_lab` and `sample_docs/test_lab` paths; the separate demo folder presents copies of the same sources under datasets and procedures.

## The 15-minute presentation

| Time | Action | Point to demonstrate |
|---|---|---|
| 0:00–1:00 | Open Overview, then System & upgrades | One entry point, visible machine requirements and update choices. |
| 1:00–3:00 | Add the three RF procedure revisions | Explicit approval, source identity and revision metadata. |
| 3:00–6:00 | Preview, save and analyze RF-TRIP | Preserved evidence, unit-labeled plots and measured findings. |
| 6:00–8:00 | Ask the RF question, then approve a review draft | Traceable guidance and the named human decision gate. |
| 8:00–10:00 | Preview UNITS and QUALITY | Mixed unit normalization and declared quality expectations. |
| 10:00–13:00 | Upload and explicitly repair damaged_capture.csv | Corruption blocks saving; only chosen changes create a reviewed copy. |
| 13:00–15:00 | Preview BAD-UNIT; download evidence and reviewed report | Incompatible dimensions are blocked, and results remain auditable. |

### 1. Add guidance and an excluded draft

Open **Test Lab → Procedures**. Under **Choose a fictional procedure**, add each of these individually:

| Source filename | Title | Version | Exercise approval choice |
|---|---|---|---|
| `rf_trip_rev_a.md` | RF cavity trip evidence review | LAB-A | Check **Use this fictional document as approved guidance in this demo workspace**, then **Add procedure to my library**. |
| `rf_trip_rev_b.md` | RF cavity trip evidence review | LAB-B | Check the same approval acknowledgement, then add. |
| `rf_trip_draft_c.md` | RF cavity trip evidence review | LAB-C-DRAFT | Add as the supplied unapproved draft. It must remain excluded from answers. |

Alternatively, feed the actual files from the separate demo folder into **Procedures → Add procedures · PDF, text, or Markdown**. Upload one file at a time, enter the title and **Version / revision** above, and check **These files are approved for use as procedural guidance** only for A and B. Click **Add files**. Multiple uploads share one revision field, so separate uploads keep the three different revision labels accurate.

Show **Stored documents** and **Inspect document inventory**. Draft C should have zero searchable chunks. Both approved revisions may be retrieved: the application does not automatically supersede A when B is added.

Presenter line: “A document is preserved separately from the decision to make it searchable guidance.”

### 2. Acquire and analyze the RF evidence

Open **Test Lab → Datasets**, choose **RF trip with recorded interlock** (`RF-TRIP`, source `rf_trip.csv`) and click **Preview this example**. Review **Preset mapping and expected issue codes**. Four columns are measurements; `RF_INTERLOCK` is a category. Preview does not write an event.

Inspect the waveforms and labeled units: cavity field is stored in V/m, power in W and tuner pressure in Pa. Then click **Save example to my workspace** and **Open this investigation**. The saved event is `LAB-RF-TRIP`.

In **Investigation → 1 · Evidence**, show the recorded interlock, plots and **Metadata, provenance, states and logs**. Leave **Normalize signals** unchecked when discussing physical values; that checkbox rescales the display for comparison and is separate from physical unit conversion.

Open **2 · Analysis**, click **▶ Run analysis**, and inspect the findings. The fixture has a recorded reference at **0 s**, a **100 Pa** pressure increase and an approximate field threshold crossing of **25 ms**. The crossing is descriptive, not a fitted cavity parameter. Simultaneous interlock, pressure and power observations do not establish a root cause.

For a direct file upload instead, use **Data workspace → Import data → Choose CSV or TSV** and select `rf_trip.csv`. Set **Engineering domain** to **RF / SRF**, verify `time_s` as **Time column** with **Seconds (s)**, keep the four physical columns as **Measurement**, and set `RF_INTERLOCK` to **Category / state**. Verify the channel names `cavity_field`, `reflected_power`, `forward_power` and `tuner_pressure`. Review the ready-to-save preview, click **📥 Import dataset**, then **Open imported event in Investigate**. This route creates its own event identity; select the imported capture by its name rather than expecting the Test Lab's fixed ID.

Presenter line: “The original capture is evidence; analysis adds a derived view without silently rewriting that capture.”

### 3. Retrieve guidance and make a human decision

In the RF investigation's **3 · RAG context**, replace **Question** with:

> RF cavity trip reflected power tuner pressure evidence review

Click **Ask the document assistant**. Inspect the retrieved source excerpts, document identifiers and revision labels. Confirm that no retrieved source is LAB-C-DRAFT and that `DRAFT-ONLY-CANARY` does not appear in the retrieved excerpts. A/B may both be cited; which excerpts rank first can vary. The local model generates an answer from retrieved passages. Check the citations and text against the approved revisions; a citation does not by itself prove the interpretation is correct.

Open **4 · Human review**, put the same question in **What should the draft focus on?**, and click **Generate new review draft**. Show the draft, then open **Knowledge library**: merely generating a draft must not create an approved knowledge record.

Return to the RF review. Select **Approve**, enter a clearly fictional reviewer such as `Demo Reviewer, training facilitator` in **Reviewer full name and role**, add a short evidence-based **Review notes** entry, acknowledge **I reviewed the evidence and source context, and I take responsibility for this decision.**, then click **Submit human decision**. Open **Knowledge library** again and inspect the new record's named review and source references. Download **Download reviewed report** if desired.

Presenter line: “A draft becomes reusable knowledge only after a named human decision.”

### 4. Show conversion and quality checks

In **Test Lab → Datasets**, preview **TSV with mixed scales and offset units** (`UNITS`, `mixed_units.tsv`). The preset explicitly maps the ISO datetime column, `voltage_unit` helper and narrative note. Check these normalized measurement values:

| Channel | Stored unit | Expected values |
|---|---|---|
| voltage | V | 1, 2000, 0.5 |
| temperature | K | 273.15, 293.15, 373.15 |
| pressure | Pa | 1000, 2000, 1000 |
| fraction | 1 (dimensionless) | 0.25, 0.5, 1 |

Then preview **Gap, jump and flatline expectations** (`QUALITY`, `gap_jump_flatline.csv`). Expand the preset to show the assumptions: expected interval 1 s; required channels voltage, temperature and vacuum; voltage maximum 10 V and stability tolerance 2 V; temperature repeated-sample threshold 5.

The expected L2 codes are `RECORDING_GAP`, `MISSING_CHANNEL`, `OUT_OF_BOUNDS`, `STABILITY_EXCEEDED`, `FLATLINE_RUN` and `BASELINE_CHANGE`. The declared missing vacuum channel is an expectation supplied by the fixture, not something inferred from the file. Valid recorded readings are retained. These flags invite review; they do not prove sensor failure or negligence.

For raw upload, see the exact settings under “Manual import references” below. A raw upload without those declared rules is not expected to produce every preset-dependent flag.

### 5. Demonstrate a blocked capture and explicit repairs

Preview **Damaged capture requiring explicit repairs** (`REPAIR`, `damaged_capture.csv`) in **Test Lab** first. The original is blocked: a duplicate, missing token, invalid numeric cell and malformed row are present. There is no successful-save button for this invalid preview.

Download the example or use the separate demo folder's file. Open **Data workspace → Import data**, upload `damaged_capture.csv`, and review the preserved original-file report. Under **Optional repairs · your choice**, explicitly select these four repairs:

1. **Remove redundant exact duplicate rows**.
2. **Mark recognized missing-value tokens as empty** for `voltage [V]`.
3. **Mark selected invalid measurements as empty**, with **Source row numbers to change** set to **6** and column `voltage [V]`.
4. **Exclude selected malformed rows from the derived copy**, with source row **8**.

Source row numbers include the header and refer to the original physical lines. The UI automatically checks the selected derived copy again. If the malformed row initially prevents column mapping, select its explicit exclusion first, then review the remaining offered repairs.

Set **Engineering domain** to **General evidence**, `time_s` to seconds, `voltage [V]` to **Measurement** named `voltage`, and `note` to **Text / log message**. Verify the numeric readings retained are exactly **1, 2, 5, 7 V**, and that unrelated narrative text survives. Do not select **Skip invalid entries and report counts** as a substitute for this explicit repair exercise.

Click **📥 Import dataset**, open the investigation and inspect the **Saved repair receipt**, preserved original-file report and reviewed-copy report. Original errors remain in the historical original report; they do not mean the repaired copy is invalid. No missing measurement is filled or interpolated. The original source bytes remain unchanged.

Presenter line: “The app makes questionable input visible and records my exact choices; it does not fabricate missing measurements.”

### 6. Finish with a useful rejection and export

Preview **Incompatible physical dimensions** (`BAD-UNIT`, `incompatible_units.csv`). Its pressure-valued header conflicts with voltage suffixes. Validation must block it and create no event. A blocked result is the successful outcome for this negative test.

Return to a saved investigation's **1 · Evidence → Event files**. Select the source, click **Prepare evidence download**, then **Download original evidence**. **Inspect attachment inventory and checksums** records its checksum. For a repaired event, standardized exports describe the reviewed event; use the original attachment download when claiming unchanged source bytes.

In **2 · Analysis**, the analysis JSON, feature table CSV and available timeline CSV are downloadable. The reviewed record in **Knowledge library** supplies a Markdown report and knowledge JSON.

## Manual import references

The per-file JSON references contain the same manifest `options` used by Test Lab/API ingestion. They are not a second upload that the dashboard merges automatically. Set these controls explicitly when using raw files:

| File / route | Mapping and settings to verify |
|---|---|
| `mixed_units.tsv` / **Data workspace → Import data** | Time `datetime`, format **Date and time**. `voltage` Measurement with **Per-row unit column for voltage** = `voltage_unit`; `voltage_unit` Ignore. `temperature [F]`, `pressure [kPa]`, `fraction [%]` Measurement, named temperature/pressure/fraction. `note` Text / log message. Header/cell units must remain physically compatible. |
| `gap_jump_flatline.csv` / **Import data** | Time `time_s`, seconds. Measurements named voltage and temperature. In **Optional quality expectations**, enable **Check expected sampling interval** = 1; enter `voltage, temperature, vacuum` under **Required channels (optional, separated by commas)**. Select voltage and temperature under **Channels with declared limits or stability**. Enable voltage **Maximum** = 10 and **Expected to remain stable** with **Allowed absolute variation** = 2. Enable temperature **Check repeated identical samples**, count 5. |
| `cryo_temperature.csv` / **Import data** | General evidence; measurements named helium_temperature and helium_pressure; `mode` Category / state; `note` Text / log message. Expected interval 1 s. Select helium_temperature and declare minimum 4 K, maximum 4.3 K, expected stable, tolerance 0.05 K. The tolerance is a temperature difference: do not add 273.15 to it. |
| `field_emission.csv` / **Import data** | RF / SRF; time `time_ms`, milliseconds. `gradient` Measurement, per-row units `gradient_unit`; helper column Ignore. `xray [counts/s]` Measurement named xray; `conditioning_phase` Category / state. |
| `plc_sequence.csv` / **Import data** | PLC / Controls; time `time_s`, seconds. `PLC_STATE` and `permit` Category / state; pressure Measurement named pressure; note Text / log message. |
| `mechanical.json` / **Data workspace → Event JSON** | Use **Choose an event JSON file**, then **Import event JSON**. This is a native EngineeringEvent with its own sampling grids and provenance, not a generic table for the CSV importer. |
| `operator_shift.log`, `operator_note.pdf` / **Data workspace → Text & PDF** | Use **Choose text or PDF evidence**, choose PLC / Controls for the log or General evidence for the PDF, inspect extracted source text, then **Save text evidence event**. The PDF contains selectable text; this is not OCR or PDF table/image analysis. |
| `row_order.csv` / **Import data** | Keep **Use row order** when no recorded time column exists. Descriptive evidence may be shown, but physical durations, rates and spectra must not be invented. |

## Additional scenarios for a longer demo

| Scenario / source file | Action and expected result |
|---|---|
| RF-XRAY / `field_emission.csv` | Save and analyze. Gradient spans 5,000,000–15,000,000 V/m; X-ray peak is 90 counts/s; fixture correlation is 1. This describes co-variation, not proof of field emission or a safe gradient. Generate a draft and **Escalate** it; no approved knowledge record is created. |
| CRYO / `cryo_temperature.csv` | First values are 4.15 K and 100000 Pa. The deliberately omitted 12–15 s interval and declared bound/stability differences are flagged. Cryogenic evidence uses the generic descriptive processor. |
| PLC / `plc_sequence.csv` | Save and analyze. RUNNING → WARNING → INTERLOCKED transitions occur at 4 and 7 s; 21 text records survive, with INFO/WARNING/ERROR labels. Review with **Correct**, change **Corrected summary**, retain observations, then submit a named decision. The corrected result enters Knowledge library. |
| MECHANICAL / `mechanical.json` | Save and analyze the native event. Original 200 Hz vibration and 20 Hz temperature grids remain distinct; derived alignment and approximately 12 Hz post-event spectrum are shown, with higher post-event RMS and temperature normalized to K. |
| UNTIMED / `row_order.csv` | Preview explicit row-order coordinates and descriptive fallback, without claimed physical timing. |
| LOG / `operator_shift.log` | Retain four timestamped lines and explicit PLC_STATE, permit and operator_action categories. Sequence analysis must not invent numeric waveforms. |
| PDF-NOTE / `operator_note.pdf` | Preserve selectable narrative text and page provenance. Untimed headings/footer lead to explicit row-order fallback. |
| DBM / `unsupported_dbm.csv` | Unsupported logarithmic dBm is blocked. Never fix it by relabeling the numeric values W; a reviewed physical conversion is needed outside this implementation. |
| Procedure retirement | In **Procedures**, select `rf_trip_rev_a.md`, acknowledge deletion and click **Delete this document**. Re-ask the RF question: LAB-A is retired from current retrieval; LAB-B remains. Saved historical review reports retain their source references. |
| Attachment lifecycle | In a fictional investigation's **Event files**, attach a separate supporting file using **Preserve event files**; download it; select it and explicitly **Delete this evidence file**. Attachment deletion leaves the event measurements available. |
| Persistence | Stop with Ctrl+C and restart using **START_LIVE_DEMO.cmd**. Reopen a saved event, analysis and reviewed knowledge record in Demo_Workspace_AI. Previously deleted procedure A must remain retired. |

The other procedure files are `rf_xray_scan.md` (RF X-ray gradient scan review), `plc_sequence.md` (PLC controls state sequence review), `mechanical_vibration.txt` (Mechanical vibration bearing review) and `cryo_review.pdf` (Cryogenic helium temperature pressure review). Their exercise version is **LAB-1** and they may be explicitly approved in the demo. The PDF procedure supports page-based citations and an exact-original download. Add them individually through Test Lab or Procedures as above.

## Repeat, clean up and verify

Test Lab event IDs are stable (`LAB-...`); a repeated save with the same ID is rejected so prior evidence cannot be overwritten. For a repeat presentation, use a fresh extracted copy, choose a new identity through a supported import/API route, or explicitly delete only the fictional event in **Data workspace → Dataset library → Delete this dataset → Confirm delete → 🗑 Delete dataset**. Event deletion also removes its associated files, analysis, drafts, reviews and knowledge. Restarting the demo launcher preserves progress; it does not reset or reimport files.

For a complete reset, use **Reset project data** in the sidebar **only after launching START_LIVE_DEMO.cmd and confirming you are in the demo workspace**. Read its current counts, check **I understand that this permanently deletes the project data listed above.**, type **RESET** exactly into **Type RESET to confirm**, then click **Reset project data**. This permanently removes all uploaded procedures/data and derived records in Demo_Workspace_AI. Code, configuration and bundled samples remain; a minimal reset audit receipt is retained. Refresh other open dashboard sessions afterward. Do not use this demonstration step in the normal workspace.

Before or after presenting, stop the live launcher and double-click **RUN_DEMO_CHECKS.cmd** in the bundle root. It checks setup and executes the actual application API against the separate Live_Demo_Data manifest in temporary isolated storage with mock/hash/SQLite providers. It does not call the live server or reset either saved workspace. Read `Demo_Check_Results/TEST_LAB_RESULTS.md` for the actual grouped check count and outcomes. The shipped fixture suite exercises 32 grouped outcomes, including all 13 datasets, procedure approval/revision behavior, named review, persistence and deletion; these are grouped assertions, not a coverage percentage. The application folder's **Run Test Lab.cmd** remains available for checking its own bundled fixture copy.

For an audience, keep three downloadable artifacts: the original RF capture, its analysis JSON and the reviewed knowledge report. Together they show the chain from source evidence through processing and retrieved guidance to a human-reviewed outcome.

This demo does not connect to EPICS or operate equipment, validate causal diagnosis, certify real procedures, test every hardware architecture or certify local AI model quality.
