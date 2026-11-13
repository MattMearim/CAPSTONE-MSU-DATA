# FRIB Decision Support

A local, human-supervised engineering decision-support prototype. The complete workflow is raw evidence -> engineering analysis -> approved-document retrieval -> draft -> Approve / Correct / Escalate -> searchable reviewed knowledge.

See [the complete workspace workflow](docs/PRODUCT_WORKFLOW.md) for model setup, acquisition, optional AI quality review, chart controls, engineering analysis, cited answers and human review. AI settings now uses four compact views; the sidebar Live resources switch hides telemetry and remembers your preference.

L1/L2 now include a full-file quality review, confirmed or suggested unit mappings, explicit derived-copy repairs, missing-recording checks and configurable stability/bounds checks. Original uploads remain unchanged. See [the quality guide](docs/DATA_QUALITY_GUIDE.md) and the deliberately imperfect `sample_data/quality_review.csv` example.

## Run it on macOS

Double-click **START_FRIB.command** in the outer project folder, or **Start FRIB.command** in this source folder. That one launcher prepares missing Python dependencies, the private Ollama runtime, **qwen3:8b** and **all-MiniLM-L6-v2**, starts the API and dashboard, and opens the app. First setup needs internet and several gigabytes of disk space; later launches reuse the installed environment and cached models. The launcher requires 64-bit Python 3.11–3.13 and keeps AI models and tools in a permanent per-user folder shared by project copies; `.frib` holds each project's startup state and environment. **SETUP_LOCAL_AI.command** (or inner **Setup Local AI.command**) is an optional setup/repair command, not a prerequisite. See [the macOS setup guide](docs/MACOS_SETUP.md).

Normal interactive launches show a native startup window with real stages, **Show details**, **Retry**, **Open workspace** and **Stop workspace**. Keep that window open during use. Headless checks and `--no-browser` stay in the console; `FRIB_NO_GUI=1` explicitly selects console mode. The most recently opened normal launcher has priority across project copies: it safely stops the older FRIB workspace, then starts the selected project and its own saved-data directory. Keep the newest startup window open; it owns the new workspace controls. Ordinary restarts and copy switches do not require manually finding an older window or pressing Ctrl+C. See [the single-instance startup guide](docs/SINGLE_INSTANCE_STARTUP.md).

Bottom-of-page **Next / Back** controls preserve your selected dataset and investigation tab. They also follow the active first-use tour. Answers have a side-by-side source viewer: use a citation's **View passage** button to see the highlighted retrieved excerpt, revision and location. Evidence, procedure content and AI interpretation retain separate labels. Navigation and source selection do not save or approve findings or call the AI again.

**Add data → Bulk import** accepts a ZIP of a folder or file collection, with background progress, safe cancellation and a per-file report. Batches support up to 1,000 files / 1 GiB expanded, with 20 MiB per data or procedure file. Uploaded procedures remain unapproved. Larger catalogs use indexed lookups and memory-bounded retrieval; only the active data tab runs. See [the bulk import guide](docs/BULK_IMPORT_GUIDE.md).

Open **Connections** for a local, interactive 3D web of saved datasets, findings, procedures, drafts and reviewed knowledge. Rotate, zoom, search and select an idea to see its relationships and open its original record. Lines come from saved citations, review history and tags; they do not imply causation. The viewer needs no external libraries or AI downloads. The refreshed interface includes subtle motion and responsive cards; use **Appearance → Gentle motion** or system Reduce Motion for a calmer view. See [the interface guide](docs/UI_WORKFLOW_GUIDE.md).

The normal workspace is `data-local-ai`; the outer presentation launcher uses `Demo_Workspace_AI`. If `data/frib.db` exists and `data-local-ai` does not, first setup copies the normal workspace and re-embeds its approved document chunks. The original `data` folder is untouched; an existing destination is never overwritten. `Demo_Workspace` is retained but not migrated automatically, so add presentation procedures to `Demo_Workspace_AI` when needed.

## Run it on Windows

Double-click **Start FRIB.cmd** in this folder, or **START_FRIB.cmd** in the outer FRIB folder. On supported 64-bit Windows, it detects a suitable Python runtime, installs a verified private runtime if needed, checks all required dependencies and installs missing requirements automatically. Internet access is needed for first setup and requested updates. Keep its window open. Press Ctrl+C to stop both services.

The dashboard opens at http://127.0.0.1:8501. The API is at http://127.0.0.1:8000/docs.

From PowerShell, `& '.\Start FRIB.cmd' --check` verifies installation without taking over the active workspace. Normal launchers keep one active FRIB workspace across project copies; the latest launch safely replaces an older FRIB run. An unrelated application occupying a port is left alone and produces an explanation; FRIB does not silently start a second workspace on alternate ports. These commands also work when no Python is on PATH.

For a fresh copy, extract the complete project ZIP first and run **Start FRIB.cmd** from the extracted folder. The archive includes source, tests, schemas, guides and three ready-to-import JSON/CSV examples in `sample_data`. It creates fresh runtime storage; your existing local data stays in the current project folder. The tested Windows Python 3.13 direct package versions are recorded in `requirements-tested.txt`.

Open **Addition items → System status** for the detected hardware, installed components, their purpose and upgrade choices. Updates are queued and applied at the next normal launch, after the handoff has stopped older FRIB workers, in a separate environment with dependency and import checks before activation. Full functional tests run separately. See [the system and startup guide](docs/SYSTEM_AND_UPGRADES.md) for supported systems, offline behavior and recovery.

For the advanced Python commands below, copy **Active interpreter** from **Addition items → System status → Hardware details**, then set this PowerShell variable to that exact path from the project folder:

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
```

Replace the placeholder before running commands. A retained `.venv` may be inactive after an upgrade; refresh this path after another upgrade. Stop FRIB before changing installed packages.

## What works

- Configurable, reproducible RF/SRF, mechanical vibration, and PLC synthetic datasets.
- CSV import with explicit time/signal mapping and JSON event import. Original uploads are preserved separately with SHA-256 checksums.
- Mixed CSV ingestion: numeric quantities, categorical/boolean states and text logs, with a validated preview and row/column error messages. TXT/MD/LOG and text-based PDF evidence import includes recorded text, severity and state summaries.
- Built-in compatible-unit conversion, mixed per-row units and canonical SI measurement storage, preserving originals and conversion history. Original and standardized exports are available separately.
- Interactive labeled plots with editable titles, channel labels, visible channels, time/record windows, category timelines and severity filters; each measurement has its own unit axis.
- Event evidence attachments: CSV, JSON, logs, text, PDF, screenshots and photos; upload, list, download and confirmed deletion.
- Dataset preview, downloads and confirmed deletion of the dataset and its derived records.
- Timestamp-based waveform alignment, recorded cleaning steps, engineering features, FFT spectra, timelines, pressure overlays, RF forward/reflected comparisons and optional X-ray/gradient trends.
- PDF/TXT/Markdown document library: multiple uploads, title/version, original download, checksums, search and confirmed deletion. Unapproved files are stored but never retrieved by the assistant.
- Persistent local search. Files and indexed passages survive restart, and deleted passages stay deleted.
- Cited source passages with document/chunk IDs, page and version. The interface separates evidence, procedural context and AI interpretation.
- Human review with editable fields, a named reviewer and explicit acknowledgement. Drafts resume after restart; repeat approval cannot publish duplicates. Original and corrected drafts are retained in review audit snapshots.
- Searchable reviewed knowledge, downloadable reports, analysis JSON/CSV and an audit history.

## Real local AI and semantic retrieval

The application defaults to **Ollama qwen3:8b** for generation, **sentence-transformers all-MiniLM-L6-v2** for embeddings and **SQLite** for persistent vectors and records. SQLite is a storage engine, not a substitute embedding model. The ordinary and fictional-data launchers use these real providers and check their readiness. A missing model or unavailable service produces an explicit error instead of a mock/hash fallback.

On macOS, the ordinary **Start FRIB.command** launcher automatically prepares missing tools and models before opening the app. On macOS, these files stay in `~/Library/Application Support/FRIB`: `tools/ollama` contains Ollama, `models/ollama` contains Qwen, and `cache/huggingface` contains the embedding model. Re-extracting or moving the project reuses this storage. An available model skips the download step, including during setup/repair. Set `FRIB_AI_HOME` to choose a different permanent location. From Terminal, run `bash 'Start FRIB.command'`. The separate **Setup Local AI.command** is available for setup or repair without opening the app. On Windows, run Ollama with the configured `qwen3:8b` model available; the launcher installs the Python requirements, while the automatic private Ollama installer is for macOS. All ordinary runs use `data-local-ai` unless you set a different `FRIB_DATA_DIR`.

### Change or upgrade the AI without coding

For the installed Windows workspace, use **START_PROJECT.cmd** at the workspace root. Its runtime, packages and models live in the separate `dependencies` folder. Open **AI settings → Main AI**, pick a named or installed model, and click **Apply model**. Missing catalogue downloads, tests and switching are automatic. **Resources** shows measured RAM, CPU, GPU and storage use. To let hardware determine the model, select **Advanced → Hardware** and click **Optimize AI for this computer**. Keep **Automatically adapt when my hardware changes** selected to prepare a newly fitting model after an upgrade. Progress, cancellation, automatic resume and Pause are available in the UI. The bundled workspace launcher is required for automatic engine/download management.

**Advanced** offers Ollama or LM Studio, installed models, custom local server settings and saved profiles. Saved choices apply to new answers/drafts immediately and persist across starts. The document embedding model and search index stay separate. See [AI settings guide](docs/AI_SETTINGS.md).

**Models** accepts a new Ollama model name/tag or official library link, downloads it and tests it before replacing the main AI or separate quality-agent role. Unused models can be deleted with a preview and confirmation; assigned models are protected. **Quality agent** has an on/off toggle, automatic incoming-data review and a separately selected model. Its read-only investigations produce tentative purple graph flags with inspected sample evidence and coverage. Named human approval is required to execute a validated repair into a new copy. It does not use RAG. See [Data Quality Agent guide](docs/DATA_QUALITY_AGENT.md).

Explicit environment variables override saved AI profiles, which override YAML. `.env.example` and `.env.demo` show real-provider defaults; local startup reads YAML, saved profiles and the process environment. Baseline settings use Ollama/Qwen3 with `FRIB_EMBEDDING_PROVIDER=sentence_transformers`, `FRIB_EMBEDDING_MODEL=all-MiniLM-L6-v2` and `FRIB_VECTOR_PROVIDER=sqlite`. The bundled launcher no longer pins the chat provider/model. Keep the embedding provider/model consistent with an index. Never point the new semantic model at an old hash index. Only isolated automated tests select explicit test doubles.

Generated drafts can include tentative evidence patterns and citations. These are not probabilities or confirmed causes. Read the sources and submit a named human review before publishing knowledge.

Python packages are also kept in the permanent FRIB folder under **python**. A fresh project copy with the same Python installation and package requirements reuses them without downloading; its small local environment points to that copy's source files. Existing working environments remain usable. Changing Python or applying package upgrades can require new compatible packages; it does not remove the saved AI models.

## Demonstrate the whole workflow

1. Open **Data workspace**, choose RF, Mechanical or PLC, and generate a dataset.
2. Open **Investigation** and run Level-2 analysis. Inspect features, warnings, waveforms, spectrum and timeline.
3. Open **Procedures** and upload a reference document. Mark it approved only when appropriate. The bundled `sample_docs` are explicitly fictional examples.
4. Open **Assistant** and ask about the indexed content, optionally selecting an event.
5. Open **Human review**, generate a draft, read the evidence and source references, then approve, edit/correct or escalate it.
6. Find approved/corrected results in **Knowledge library**. Escalated drafts never become searchable knowledge.
7. Restart, verify the files and review status persist, then try the confirmed delete controls on disposable examples.

Optional fictional demonstration seeding: `& $fribPython scripts/seed_demo.py`, using the active interpreter set above. This is idempotent and explicitly indexes the bundled fictional documents for a demo workspace.

## Start again with an empty workspace

Open **Reset project data** in the sidebar to review the saved-data counts, acknowledge permanent deletion, type **RESET**, and confirm the reset. It clears datasets, original uploads and attachments, procedures and their retrieval index, analyses, drafts, reviews, published knowledge and previous audit history. One minimal reset receipt remains. The application, configuration, logs, installed models and bundled sample files are retained.

Reset applies to the running application's data directory, including a custom `FRIB_DATA_DIR`; the default local-AI directory is a separate workspace from the retained legacy `data` folder. It does not automatically recreate demonstration records. Generate or import a new dataset when ready. See [the reset guide](docs/RESET.md) for the exact scope, verification and isolated tests.

## Standalone generator

No language model is initialized:

```powershell
& $fribPython scripts/generate_event.py rf --seed 42 --output rf-example.json
```

Choose `rf`, `mechanical` or `plc`. `--overrides` accepts a JSON object. `--store` also adds the generated event to the local application. Existing output files and stored event IDs are never overwritten.

## Present and verify L1/L2

The [presenter guide](docs/presentation/PRESENTER_GUIDE.md) gives a 12–15 minute live walkthrough and an appendix covering the remaining features. The [feature inventory](docs/presentation/FEATURE_COVERAGE.md) maps capabilities and issue codes to exact test selectors and states their boundaries.

Using the active interpreter set above, run `& $fribPython scripts/run_l1_l2_demo.py --output presentation_evidence` to execute the isolated demonstrations and save their inputs, assertions and actual outputs. Run pytest with `--junitxml=presentation_evidence\pytest-results.xml`, then `& $fribPython scripts/build_l1_l2_showcase.py --evidence presentation_evidence --junit presentation_evidence\pytest-results.xml --output presentation_evidence\Feature_Showcase.html` to produce an offline, searchable presentation. Install the development extras below first if pytest is unavailable. The runner uses temporary application storage. The HTML presents recorded evidence without needing the API, a model service or internet access.

## Validate and deploy

```powershell
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest -q
```

The tests use temporary data, including document upload/deletion/restart, evidence originals, review gates and numerical checks for all three domains. The UI tests exercise pages, file controls and review corrections without contacting real services.

Docker: `docker compose up --build` starts Ollama, downloads the configured model through the model-setup service, and runs the backend with semantic embedding dependencies. Model weights and embedding downloads persist in named volumes; records use `./data-local-ai`. First startup requires internet and model storage. API readiness is checked before the dashboard starts. Docker builds and real-model quality require validation on the intended host.

## Scope and requirements

See [the mixed-ingestion guide](docs/INGESTION_GUIDE.md), [requirements matrix](docs/REQUIREMENTS_MATRIX.md), [validation plan](docs/VALIDATION_PLAN.md) and [start guide](START_HERE.md).

This is a capstone prototype with synthetic validation, rather than a commissioned FRIB operating system. Live EPICS/archive/LLRF acquisition, official approved FRIB procedures, sponsor-approved physical models and tolerances, expert assessment of AI answers, authentication/roles and field-emission conditioning-effect validation remain deployment work. The application provides no accelerator control or autonomous corrective actions. Citation presence is checked; it does not establish the truth of a model's interpretation.

Original event files are immutable while stored. A confirmed dataset deletion permanently removes its files, analysis and knowledge records; audit history remains. A full project-data reset also clears previous audits and procedures, retaining only its minimal reset receipt. Back up the entire data directory while FRIB is stopped to preserve both files and SQLite databases.

## Built-in Test Lab

The sidebar's **Test Lab** contains 13 reproducible fictional datasets and seven procedures across CSV, TSV, native event JSON, logs, text, Markdown and selectable-text PDF. Browse expected results, preview without storing records, and save examples explicitly for investigation. Inventory tables are optional detail views; Signals, States and Notes have focused interactive views.

Maintenance checks do not stop or take over the active workspace. If missing test-runner dependencies cannot be prepared safely while an environment is in use, the check explains that limitation. Double-click **Run Test Lab.cmd**, or run `& '.\Start FRIB.cmd' --test-lab --output test_lab_results` from PowerShell to check setup automatically and exercise 32 grouped real API checks in temporary storage. See [docs/TEST_LAB.md](docs/TEST_LAB.md) for exact expected values, revision/approval behavior and the presentation walkthrough. Tests use mock answers, hash retrieval and SQLite; operational FRIB integration and local AI providers require separate validation.
