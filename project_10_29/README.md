# FRIB Decision Support

A local, human-supervised engineering decision-support prototype. The complete workflow is raw evidence -> engineering analysis -> approved-document retrieval -> draft -> Approve / Correct / Escalate -> searchable reviewed knowledge.

L1/L2 now include a full-file quality review, confirmed or suggested unit mappings, explicit derived-copy repairs, missing-recording checks and configurable stability/bounds checks. Original uploads remain unchanged. See [the quality guide](docs/DATA_QUALITY_GUIDE.md) and the deliberately imperfect `sample_data/quality_review.csv` example.

## Run it on Windows

Double-click **Start FRIB.cmd** in this folder, or **START_FRIB.cmd** in the outer FRIB folder. On supported 64-bit Windows, it detects a suitable Python runtime, installs a verified private runtime if needed, checks all required dependencies and installs missing requirements automatically. Internet access is needed for first setup and requested updates. Keep its window open. Press Ctrl+C to stop both services.

The dashboard opens at http://127.0.0.1:8501. The API is at http://127.0.0.1:8000/docs.

From PowerShell, `& '.\Start FRIB.cmd' --check` verifies installation. If ports are occupied, use `& '.\Start FRIB.cmd' --api-port 8002 --port 8502`. These commands also work when no Python is on PATH.

For a fresh copy, extract the complete project ZIP first and run **Start FRIB.cmd** from the extracted folder. The archive includes source, tests, schemas, guides and three ready-to-import JSON/CSV examples in `sample_data`. It creates fresh runtime storage; your existing local data stays in the current project folder. The tested Windows Python 3.13 direct package versions are recorded in `requirements-tested.txt`.

Open **System & upgrades** for the detected hardware, installed components, their purpose and upgrade choices. Updates are queued and applied at the next launch in a separate environment, with dependency and import checks before activation. Full functional tests run separately. See [the system and startup guide](docs/SYSTEM_AND_UPGRADES.md) for supported systems, offline behavior and recovery.

For the advanced Python commands below, copy **Active interpreter** from **System & upgrades → Hardware details**, then set this PowerShell variable to that exact path from the project folder:

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

## Default demo mode and optional local AI

The default is `mock` + `hash` + `sqlite`: no AI model download, model service or account is required. The assistant returns actual retrieved excerpts, clearly marked as demo mode. Knowledge drafts include tentative evidence patterns ranked by supporting observations and contradictions. These ranks are not probabilities or confirmed causes. Hash search has limited relevance and does not validate engineering conclusions.

For local model generation, set `$fribPython` as above, stop FRIB, and install optional packages with `& $fribPython -m pip install -e ".[rag]"`. Install/run Ollama separately and make the model named in `config/models.yaml` available. Then run `& '.\Start FRIB.cmd' --local-ai`. This uses a separate `data-local-ai` directory to keep semantic vectors and demonstration data separate. First-time semantic model loading can require internet access. The model can be changed in YAML or with `FRIB_LLM_MODEL`.

Advanced provider overrides: `FRIB_LLM_PROVIDER=ollama|lmstudio|mock`, `FRIB_EMBEDDING_PROVIDER=sentence_transformers|hash`, `FRIB_VECTOR_PROVIDER=sqlite|chroma|memory`. Keep the embedding provider/model consistent with an index; use a separate `FRIB_DATA_DIR` when changing embedding models. Environment variables override YAML. `.env.example` is a template for Docker Compose; local startup reads YAML and the process environment.

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

Reset applies to the running application's data directory, including a custom `FRIB_DATA_DIR`; the optional local-AI directory is a separate workspace. It does not automatically recreate demonstration records. Generate or import a new dataset when ready. See [the reset guide](docs/RESET.md) for the exact scope, verification and isolated tests.

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

Docker demo: `docker compose up --build`. Ollama is an optional `local-ai` profile. API readiness is checked before the dashboard starts. Docker builds and real-model quality require validation on the intended host.

## Scope and requirements

See [the mixed-ingestion guide](docs/INGESTION_GUIDE.md), [requirements matrix](docs/REQUIREMENTS_MATRIX.md), [validation plan](docs/VALIDATION_PLAN.md) and [start guide](START_HERE.md).

This is a capstone prototype with synthetic validation, rather than a commissioned FRIB operating system. Live EPICS/archive/LLRF acquisition, official approved FRIB procedures, sponsor-approved physical models and tolerances, expert assessment of AI answers, authentication/roles and field-emission conditioning-effect validation remain deployment work. The application provides no accelerator control or autonomous corrective actions. Citation presence is checked; it does not establish the truth of a model's interpretation.

Original event files are immutable while stored. A confirmed dataset deletion permanently removes its files, analysis and knowledge records; audit history remains. A full project-data reset also clears previous audits and procedures, retaining only its minimal reset receipt. Back up the entire data directory while FRIB is stopped to preserve both files and SQLite databases.

## Built-in Test Lab

The sidebar's **Test Lab** contains 13 reproducible fictional datasets and seven procedures across CSV, TSV, native event JSON, logs, text, Markdown and selectable-text PDF. Browse expected results, preview without storing records, and save examples explicitly for investigation. Inventory tables are optional detail views; Signals, States and Notes have focused interactive views.

Stop FRIB with Ctrl+C before the automated run so any missing test-runner dependencies can be prepared. Double-click **Run Test Lab.cmd**, or run `& '.\Start FRIB.cmd' --test-lab --output test_lab_results` from PowerShell to check setup automatically and exercise 32 grouped real API checks in temporary storage. See [docs/TEST_LAB.md](docs/TEST_LAB.md) for exact expected values, revision/approval behavior and the presentation walkthrough. Tests use mock answers, hash retrieval and SQLite; operational FRIB integration and local AI providers require separate validation.
