# Start here

## Open the application

1. Double-click **Start FRIB.cmd** in this folder, or **START_FRIB.cmd** in the outer FRIB folder.
2. Wait for the dashboard to open. Keep the launcher window open while you work.
3. To stop, select that window and press **Ctrl+C**. To restart, double-click the launcher again.

On supported 64-bit Windows, the launcher checks Python and every required application dependency, creates a private environment, and installs missing requirements automatically. If no suitable Python is available, it downloads a verified official Python runtime for this project. First setup and requested updates need internet access and enough free disk space. Routine demo use needs no account, cloud service or AI model.

If the browser does not open, visit **http://127.0.0.1:8501**. If the launcher reports an occupied port, close the earlier FRIB launcher or run `python start.py --api-port 8002 --port 8502` from this folder.

## Check the computer and update software

Open **System & upgrades** in the sidebar. It shows the computer's resources, installed software and what each component does. Expand a software card to select an update, then queue the selected changes or the complete required package set. Review or cancel them in **Startup plan**. Stop FRIB with Ctrl+C and open **Start FRIB.cmd** again to apply the plan in a separate validated environment.

**Check latest versions** needs internet; local inventory does not. Optional AI dependencies have separate resource guidance and explicit installation choices. See [the system and upgrade guide](docs/SYSTEM_AND_UPGRADES.md) for setup, recovery and supported systems.

## First walkthrough

**Data workspace:** choose a domain and generate an example. Adjust the labeled settings, inspect the preview and download JSON or CSV. To use your own data, choose CSV import or JSON import. The importer preserves the original uploaded file as evidence. Numeric samples must be finite and have distinct timestamps. CSV rows can be ordered by their timestamps for the derived view, with the original order preserved in the source file; the app explains invalid input.

CSV import now accepts mixed measurements, categories, true/false states and text. Confirm the detected column roles and source units, then inspect the standardized preview before saving. Use the text/PDF tab for notes and logs. Try `sample_data/mixed_units_and_states.csv` or `sample_data/operator_shift.log`. The built-in converter and automatic SI storage prevent compatible quantities from keeping mixed scales. Read [the ingestion guide](docs/INGESTION_GUIDE.md) for examples and formats.

The **L1 quality review** flags damaged rows, invalid entries, missing cells, duplicate records and uncertain units. Review optional repairs and preview the resulting derived copy before saving; the original upload stays unchanged. Set recording cadence, required channels, bounds and stable-value tolerances in **Optional quality expectations**. **L2 capture quality** flags gaps, stuck readings, spikes and sudden changes, with locations and review guidance. Try `sample_data/quality_review.csv` and follow [the quality guide](docs/DATA_QUALITY_GUIDE.md).

**Investigation:** select a dataset. The Evidence tab shows original metadata, signals, states/logs and attached files. Upload logs, screenshots or other supporting files here. Run Level-2 analysis and examine the resulting features, processing notes, aligned waveforms, spectrum and timeline. Missing signals produce an explanation rather than a guessed calculation.

Use the plot controls to select channels, filter time or record order, edit display labels and inspect log severity. Measurements use separate axes with their units. Text-only captures receive a descriptive evidence summary. Unknown timing is labeled as record order rather than seconds.

**Procedures:** upload PDF, text or Markdown references. Give them a useful title and version. The approval checkbox starts unchecked; only approved uploads participate in assistant retrieval. Original files can be downloaded. The library includes search and explicit delete confirmation. PDFs must contain selectable text; scanned-only or password-protected PDFs need preparation first.

**Assistant:** ask about indexed content, optionally choosing an event. Default demo mode returns actual retrieved excerpts and does not generate an AI interpretation. A local model is optional. The interface shows evidence and source identifiers separately from interpretation.

**Human review:** generate a draft after analysis. Read the observations, tentative hypotheses, actions and sources. Enter your name/role and acknowledge review before submitting. Approve publishes the draft, Correct lets you edit ordinary text fields and publishes the corrected draft, and Escalate saves the decision without publishing. A reviewed draft cannot be approved a second time.

**Knowledge library:** search and download reviewed records. Files, drafts and reviewed knowledge persist when the application restarts.

## Add and delete files

- **Reference procedures:** use Procedures.
- **Evidence logs/screenshots/data files:** use Investigation -> Evidence -> Evidence files.
- **Entire datasets:** use Data workspace -> Dataset library. Deleting a dataset also removes its attachments, analysis, drafts and associated knowledge.

Every delete asks for confirmation. Deleted documents are removed from future retrieval, including after restart. Previous reports retain their historical source references and evidence snapshots. Save anything needed before deleting it.

## If something goes wrong

- **Cannot reach backend:** start the launcher, wait for readiness, then use Retry connection.
- **Python missing:** run **Start FRIB.cmd**; it installs the project's private runtime when needed. If your organization blocks downloads or PowerShell, ask your administrator to allow the official sources listed in [the startup guide](docs/SYSTEM_AND_UPGRADES.md).
- **Install failed:** check internet connectivity and the displayed error. Rerun the launcher after fixing it.
- **Model unavailable:** demo mode needs no model. Local-AI mode requires Ollama, the configured model and optional RAG dependencies.
- **Import rejected:** use increasing timestamps, equal-length signal columns and finite numeric values. A JSON event must follow `contracts/event.schema.json`; event IDs must be unique.
- **Analysis cannot find a signal:** map CSV columns to the expected signal names for your domain. RF trip analysis needs cavity_field, reflected_power and tuner_pressure; mechanical needs vibration (bearing_temperature is optional); PLC requires discrete state evidence named PLC_STATE, which the JSON example includes.

Startup logs are under `data/logs` (or `data-local-ai/logs` for local AI).

## Keep a backup

Stop FRIB, then copy the whole `data` folder somewhere safe. It contains the database, original evidence, documents and search index. Local-AI mode stores its data separately in `data-local-ai`.

For code changes, model setup, tests and Docker, read [README.md](README.md). For requirement coverage and remaining work, read [docs/REQUIREMENTS_MATRIX.md](docs/REQUIREMENTS_MATRIX.md).

## Test the whole workflow

Open **Test Lab** in the sidebar for 13 fictional datasets and seven procedures. Select a case, read its expected outcome and preview it without saving. Use **Save example to my workspace** only when you want to investigate it. Procedure approval is a separate explicit choice.

To run every Test Lab scenario automatically, double-click **Run Test Lab.cmd**. It checks setup automatically, uses disposable storage and writes `test_lab_results/TEST_LAB_RESULTS.md` plus JSON evidence. Your saved workspace is preserved. Follow [the Test Lab guide](docs/TEST_LAB.md) to present units, damaged input and repairs, gaps, state/log evidence, approved retrieval and human review.
