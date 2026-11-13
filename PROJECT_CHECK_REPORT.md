# FRIB project check — November 11, 2026

> Interface update — November 13, 2026: AI settings now uses four compact views with secondary controls in popovers. Explore opens on the chart, with lighter axes/grid styling, a compact View menu and collapsed AI review, data checks and file controls. The chart-reading and original-context explanation panels were removed. The sidebar Live resources switch removes the live iframe/polling when hidden and persists the preference across restarts. The focused interface, chart, quality-agent and provider suite passed 117 checks; the running app was also visually verified. The complete workflow is documented in `FRIB_Final_Project/FRIB_Decision_Support/docs/PRODUCT_WORKFLOW.md`. This interface update does not resolve the unrelated backend/deployment audit findings below.

> Data-quality/model-library update — November 13, 2026: the UI now accepts future Ollama model names or official library links, downloads/tests them for the main AI or independent quality-agent role, and deletes unused models with preview/confirmation and protection for both assigned roles. The separate Data Quality Agent has a persistent on/off toggle, optional incoming-data queueing, bounded read-only data tools, exact sample-evidence validation, tentative purple graph flags, named human reviews and approved repairs into separate copies with audit receipts. It does not call RAG. The feature/regression suite passed 349 checks, including on/off during inference, imports while off, reset isolation, graph coordinates, UI approval gates and original preservation. Live verification covered a real Qwen3 1.7B quality review, main Qwen3 4B inference while the agent was off, off-state persistence across restart, and deletion of a temporary model alias while retaining existing weights. The final synthetic run produced one grounded flag on the excursion; earlier trials also demonstrated missed and weak flags. These remain bounded draft findings, not a validated scientific anomaly detector. Receipts and screenshots are under `dependencies/logs/quality-*` and `dependencies/logs/model-deletion-validation.json`; see `FRIB_Final_Project/FRIB_Decision_Support/docs/DATA_QUALITY_AGENT.md`. The earlier audit's unrelated defects remain recorded below.

> Installation update — November 12, 2026: the required Python runtime, application packages, portable Ollama, Qwen model and MiniLM embeddings are now installed in the workspace's `dependencies` folder. Real model checks, API/dashboard startup, browser rendering and Stop/restart passed. Use `START_PROJECT.cmd` and `STOP_PROJECT.cmd`; see `dependencies/README.md` and `dependencies/installation-status.json`. The readiness observations below describe the earlier audit state; the source defects listed in this report were not changed by the installation.

> Feature update — November 12, 2026: AI settings now offers a one-button model picker across Qwen/Llama/Phi/Gemma and other installed models, hardware-aware automatic setup, background downloads, real chat/JSON checks, saved profiles, live switching and measured resource usage. Optional automatic matching responds to hardware upgrades. Ollama and LM Studio remain available. The latest feature/security suite passed 103 checks. UI switching Qwen → Llama → Qwen and a short measured 4B/8B comparison passed; raw measurements are in `dependencies/logs/model-resource-comparison.json`. See `FRIB_Final_Project/FRIB_Decision_Support/docs/AI_SETTINGS.md`. The original checksum and test counts below describe the pre-change audit snapshot, not the modified source.

This report reviews the supplied `FRIB_Final_Project` source bundle, version 0.4.0. Configuration, script and documentation paths are relative to `FRIB_Final_Project/FRIB_Decision_Support`. Module paths such as `api/main.py` and `processing/registry.py` are relative to its `src/frib_ds` directory. The original audit was an inspection and verification task; the subsequent AI settings feature changes are recorded above.

## Overall assessment

The project implements a substantial local engineering decision-support prototype: evidence import, quality review, deterministic analysis, approved-procedure retrieval, AI drafts, human review, and persistent reviewed knowledge. It is suitable for further local demonstration and development once the runtime and models are prepared. It is not a commissioned FRIB operational system, and this audit found defects that should be addressed before relying on its analysis or Docker deployment.

The source bundle is intact: all 350 entries in the outer checksum manifest and all 291 entries in the inner manifest matched, with no missing files. Static parsing found no Python syntax errors. There are 70 Python source modules, 63 test modules, and 685 test functions before parametrization.

Current execution results are recorded in the verification section below. Historical reports under the outer `Verification` folder describe earlier runs and configurations; they are not current acceptance results.

## What the application does

| Stage | Implemented behavior | Important boundary |
| --- | --- | --- |
| L1: evidence | Import CSV/TSV, native event JSON, logs, text, Markdown and selectable-text PDFs; preserve original bytes and checksums; map fields; convert supported quantities to SI; review quality and explicit repairs | No OCR or live acquisition. Unit suggestions and repairs need review. |
| L2: analysis | RF trip timing and field decay, pressure and power comparisons; mechanical vibration RMS/FFT; PLC chronology; descriptive summaries for incomplete or generic evidence | Numerical observations and tentative patterns do not establish physical causes. |
| L3: retrieval | Chunk approved procedures, embed them, retrieve relevant passages, return document/version/page references, optionally generate a cited answer | Unapproved procedures are excluded. Citation presence does not establish that a claim is supported. |
| L4: draft and review | Create draft findings, tentative hypotheses and review steps; Approve/Correct/Escalate with a reviewer name and dashboard acknowledgement | Approve and Correct publish knowledge; Escalate does not. Reviewer identity is self-declared; acknowledgement is enforced by the dashboard, not an API request field. |
| Supporting tools | Saved investigations, downloads, attachments, knowledge search, audit history, connections graph, tutorial, Test Lab, system information, staged package upgrades and guarded reset | These tools operate on a local single-user workspace. |

The bundled Test Lab has 13 fictional datasets and seven fictional procedures. The three specialized domains are RF/SRF, mechanical vibration and PLC; other measurements can use descriptive evidence processing.

## Architecture and storage

A Streamlit Python server serves the browser dashboard on port 8501 and calls FastAPI on port 8000. FastAPI validates Pydantic contracts and coordinates ingestion, quality checks, domain processors, retrieval and the knowledge service.

Main source areas:

- `dashboard/`: Streamlit screens, charts, review controls and custom browser components.
- `api/main.py` and `api/security.py`: HTTP endpoints, lifecycle coordination, request limits and local host/origin checks.
- `models.py`, `units.py`, `ingestion/`, `quality/`: validated records, conversion, parsing and data-quality assessment.
- `generator/` and `processing/`: reproducible synthetic inputs and deterministic domain calculations.
- `rag/`: document loading, embeddings, vector retrieval and Ollama/LM Studio adapters.
- `knowledge/`: draft generation, tentative evidence patterns and reviewed publication.
- `storage/`: SQLite records, original files, procedures and reset recovery.
- `start.py`, `launcher.py`, `local_ai.py`, `system_manager.py`, `scripts/`: setup, readiness, process ownership, model preparation and managed upgrades.

Default AI configuration is Ollama `qwen3:8b`, SentenceTransformers `all-MiniLM-L6-v2` embeddings (384 dimensions, CPU), and persistent SQLite vectors. Explicit test providers exist, but ordinary model failures do not silently fall back to mock answers or hash embeddings.

Normal saved records are under `data-local-ai`: `frib.db` stores catalog and workflow records; managed subdirectories hold originals, attachments and procedures; `chroma/vectors.sqlite` stores the default SQLite vector index. The folder name `chroma` does not mean the default provider is ChromaDB. Reviewed-knowledge search uses SQLite text matching, separately from semantic procedure search.

The outer presentation launcher selects `FRIB_Final_Project/Demo_Workspace_AI`. Runtime state and environments use `.frib`; models and reusable packages can use per-user FRIB storage. Back up the entire active data directory with the app stopped, so the database and its referenced files stay together. Confirmed dataset deletion cascades through its derived records; full reset also clears prior audit history and leaves a minimal reset receipt.

Configuration loads `config/*.yaml` and actual process environment variables. `.env.example` is a reference file; creating a `.env` file alone does not make this local launcher load it. Important overrides include `FRIB_DATA_DIR`, `FRIB_CONFIG_DIR`, `FRIB_API_URL`, `OLLAMA_BASE_URL`, the `FRIB_LLM_*`, `FRIB_EMBEDDING_*` and `FRIB_VECTOR_PROVIDER` settings. Changing embedding models against an existing index requires deliberate migration/reindexing.

## How to run this copy on Windows

1. Install and open [Ollama for Windows](https://docs.ollama.com/windows). The Windows FRIB bootstrap can prepare Python and Python packages, but its automatic private Ollama installer is macOS-only. Ollama's normal local API listens on port 11434.
2. In a new PowerShell window, download the configured model with `ollama pull qwen3:8b` ([CLI reference](https://docs.ollama.com/cli), [configured model](https://ollama.com/library/qwen3:8b)).
3. Start the normal workspace:

   ```powershell
   Set-Location 'C:\Users\berda\OneDrive\Documents\CHAT\FRIBCURRENTPROJECT\FRIB_Final_Project'
   & '.\START_FRIB.cmd'
   ```

4. Keep the launch window open. The app prepares its private environment, verifies real AI readiness, starts both services, checks readiness and opens the dashboard. First setup needs internet and several GB of storage. Ctrl+C stops the terminal-launched services.
5. Dashboard: <http://127.0.0.1:8501>. API documentation: <http://127.0.0.1:8000/docs>.

Useful checks from the outer project directory:

```powershell
& '.\FRIB_Decision_Support\Start FRIB.cmd' --check-packages
& '.\FRIB_Decision_Support\Start FRIB.cmd' --check
& '.\RUN_DEMO_CHECKS.cmd'
```

`--check-packages` checks package readiness. `--check` also verifies real model generation and embeddings. Both launchers can prepare missing runtime requirements rather than being purely read-only installation probes. The demo checks exercise disposable storage with explicit test providers. To use the separate real-AI presentation workspace, launch `START_LIVE_DEMO.cmd`; it does not automatically import every fictional input.

The launcher's intended behavior is one active FRIB workspace across project copies. The supplied Windows console launch chain does not establish the process group needed for automatic handoff (see finding 10). On Windows, stop the previous FRIB console with Ctrl+C before switching copies/workspaces. Unrelated processes occupying the ports should receive an explanatory conflict, rather than being stopped.

On macOS use outer `START_FRIB.command`; its private Ollama installation is supported there. Linux and Docker were not executed during this Windows audit. Docker should not be treated as working until the defects below are repaired and its full workflow is checked.

For development, use the application's active interpreter after setup and stop the app before altering its packages:

```powershell
$fribPython = 'C:\replace\with\active\python.exe'
& $fribPython -m pip install -e '.[ui,dev]'
& $fribPython -m pytest -q
```

Run these development commands from the inner source directory. The source-tree editable installation is the supported path currently described by the project; a standalone wheel omits resources required by the launcher.

## Current host readiness

The inspected machine runs 64-bit Windows 11 Home (build 26300), with an Intel i5-11400H, approximately 15.7 GiB RAM, and an NVIDIA GTX 1650 Max-Q with approximately 4 GiB VRAM. The [configured Ollama model](https://ollama.com/library/qwen3:8b) currently has a 5.2 GB model artifact, exceeding the GPU's VRAM before other runtime needs. This suggests CPU/partial GPU execution will be needed; it is not a measured performance result. Actual speed and usable context capacity require a real run.

At audit start, `python` resolved to a Microsoft Store alias and failed, `py`, `ollama` and `docker` were not available on PATH, no application runtime was prepared in this source copy, and ports 8000, 8501 and 11434 were not listening. A Python 3.12.14 interpreter bundled with Codex was located and used to create a separate audit environment. This does not mean the normal FRIB launcher has been installed or that Ollama is ready.

No real model weights were downloaded and no real Ollama inference, full normal desktop startup, Docker build/run, facility data or accelerator integration was tested here.

## Findings to address

### 1. Docker dashboard requests are rejected by the backend — high priority

`docker-compose.yml:67` sets `FRIB_API_URL=http://backend:8000`. `api/security.py:14-24,47-51` allows only loopback/local hostnames (and the test host), so the Compose service hostname `backend` receives HTTP 400. An isolated request through the actual middleware reproduced HTTP 400 for `backend:8000` and HTTP 200 for the localhost control. The backend's localhost health check can still pass, hiding the failure. Explicitly support the trusted internal hostname without weakening browser-origin protections, and test dashboard-to-backend requests in Compose.

### 2. Inferred signal timing can produce physical frequency estimates — medium priority

`quality/event_checks.py:188` recognizes signal-level `metadata.inferred_time` and emits `TIMING_UNAVAILABLE`. `processing/registry.py:20-29` does not gate domain processing on that issue and only checks the event-wide `import_summary.time_basis == 'row_index'`. An isolated native event with inferred signal timing produced a 0.129 Hz mechanical FFT result despite its timing warning; adding the event-wide row-index flag correctly withheld it. Gate timing-dependent calculations consistently on the timing quality result and affected signal metadata.

### 3. Cross-domain retrieval can hide an eligible procedure — medium priority

`rag/service.py:51-60` retrieves only `top_k * 8` global candidates and then applies event-domain filtering. At the default `top_k=5`, an isolated catalog with 40 higher-scoring ineligible PLC chunks hid a relevant approved RF passage scoring 0.8, causing an insufficient-context answer. Removing one PLC chunk made that same passage retrievable. Apply domain filtering during vector search or expand candidates until the eligible set is exhausted or sufficiently populated.

### 4. Windows bulk jobs can remain running after their owner has died — medium priority

`ingestion/bulk.py:331-344` initially treats a positive persisted owner PID as alive, then checks process existence only on non-Windows systems. A fresh Windows manager reading a synthetic prior-owner report with an impossible PID still returned `running` and retained its staged upload. A restart/crash can therefore leave an old queued/running report permanently active. Use Windows-safe process ownership/liveness or an owner lock, including protection against PID reuse.

### 5. Event and attachment deletion can leave records without evidence — medium priority

`api/main.py:503-510,609-616` removes files before deleting their database rows. Isolated API fault injection reproduced HTTP 500, retained database records and missing original files for both event and attachment deletion. A crash between operations has the same ordering risk. Procedures already have a durable deletion intent/tombstone mechanism in `storage/documents.py:95-105`; extend recoverable deletion to events and attachments.

### 6. The Docker dashboard omits its Test Lab files — medium priority

`Dockerfile.dashboard:3-5` copies metadata, source and Streamlit configuration but no `sample_data` or `sample_docs`. `dashboard/test_lab_ui.py:82` requires the manifest and its inputs. Compose does not mount them into the dashboard, so the Test Lab page cannot load. Include the fixture resources and relevant user help in the image.

### 7. Older Python 3.11 patch versions pass setup selection but cannot install Ollama — low priority

`scripts/start_unix.sh:5` accepts every Python 3.11 patch, while `local_ai.py:264` requires `tarfile.extractall(filter='data')`, introduced in 3.11.4. Require the supported capability/current patch release. See the [official Python 3.11 tarfile documentation](https://docs.python.org/3.11/library/tarfile.html).

### 8. Rebuilding a source ZIP on Windows loses executable permissions for Mac launchers — medium priority

`scripts/package_project.py:80` writes native `path.stat().st_mode` into Unix ZIP permission attributes. On Windows those files have no Unix executable bits. The cross-platform packaging test reproduced an archive containing `Start FRIB.command` with mode 0666 instead of an executable mode. The final-bundle builder preserves those inner permissions. Assign known executable launcher/script permissions explicitly when building a portable archive. This concerns a newly rebuilt ZIP, not a claim about the inaccessible Unix permission metadata of an earlier ZIP.

### 9. Concurrent bulk cancellation/status updates fail on Windows — medium priority

`ingestion/bulk.py:98` replaces the status JSON without consistently serializing the worker's persistence with cancellation/status access. Twelve isolated cancellation trials in temporary storage outside OneDrive produced seven Windows permission failures: three callers received `PermissionError` and four jobs were recorded as failed. No processor ran in any trial, so the cancellation boundary held; the status/report persistence did not. Coordinate status-file access for each job and handle Windows sharing conflicts without converting cancellation into failed imports. Evidence: `.project-audit/bulk_security_repro_results.json`.

### 10. Supplied Windows shortcuts cannot automatically hand off an existing console workspace — medium priority

`Start FRIB.cmd:4` delegates to `scripts/bootstrap_windows.ps1:191`, which directly runs `start.py` without creating a new Windows process group. `scripts/single_instance.py:309` records a usable console group only when `FRIB_STARTUP_CONSOLE_GROUP=1`; the code that sets that flag and creates the group is in `startup_window.py:76-80`, outside this Windows shortcut chain. A subsequent launch calls the termination path, and `single_instance.py:232-235` refuses to signal an owner without that group. No running-owner shutdown-request polling bypass exists. A safe injected-identity probe reproduced the explicit refusal without signalling any real process. Either establish the required Windows group/ownership path or implement a cooperative shutdown request. Until fixed, stop the previous Windows console manually before switching workspaces.

### Further maintenance and validation gaps

- The complete pytest command fails during collection on Windows at `tests/test_security_runtime.py:240`: the parameter list evaluates `signal.SIGHUP` before its POSIX-only skip can apply. The other modules were run separately. Guard construction of the signal parameter list and add Windows CI coverage.
- The declared Bandit command exits 1 with nine medium findings. Review found eight fixed SQL/placeholder constructions and one fixed HTTPS download URL rather than exploitable input flow. The existing SQL suppression is on the wrong line. Use narrowly justified per-line suppressions or simpler literal statements so the CI gate can pass while retaining the rules. See `.project-audit/source-security-triage.md` for every location.
- `config/processing.yaml` exposes `minimum_samples`, `derivative_smoothing_samples` and `mechanical.anomaly_threshold_sigma`, but the implementation does not read them. Remove them or connect them to tested behavior so editing configuration does what users expect.
- `docs/REQUIREMENTS_MATRIX.md:27` still calls Ollama an optional Compose profile. The current Compose configuration requires it. Historical verification reports also describe older mock-based launchers and older workspace locations; the current README/source should govern current setup.
- The `frib-start` entry point loads source-tree `start.py` and configuration/prompts outside the installed package. A conventional wheel-only installation is incomplete; the documented extracted-source/editable workflow avoids that issue.
- Ollama generation is fixed to a 4,096-token context and 500-token output in `rag/llm.py:47-48`, but valid questions, retrieved passages and analysis records can be much larger. Test oversized context and incomplete structured drafts with the real provider, and add explicit budgeting/truncation policy.
- Dependency constraints are broad lower bounds. `requirements-tested.txt` records an older direct-dependency snapshot and is not a full lockfile. Reproducible deployment needs a tested resolved dependency set and pinned container/runtime artifacts.
- The GitHub Actions workflow covers Linux/macOS, but not Windows, despite substantial Windows-specific bootstrap and recovery code.
- Project metadata has no license field and the source root has no `LICENSE` file. Third-party notices exist, but the application's own distribution terms are not declared.
- This folder is an extracted bundle without Git metadata; branch history, remote CI results and change provenance could not be checked.

## Security and operational boundary

Implemented protections include local Host/Origin validation; bounded multipart and chunked requests; ordinary per-file limits; bulk file-count/expanded-size/path/symlink/encryption/compression checks; controlled identifiers; parameterized SQL; CSV formula neutralization; approved-only retrieval; embedding compatibility metadata; transactional single-review publication; and preflight/recoverable reset intent with a cross-process lifecycle lock.

The intended deployment is a local single-user workspace. There are no authenticated roles, verified approval identities, signed audit records or tamper-evident storage. Original-file checksums establish recorded provenance but are not automatically revalidated on every read. PDF extraction runs in-process. Facility deployment still needs representative data, official approved procedures, calibrated units, sponsor-approved physics/tolerances, read-only acquisition adapters, access control, retention and tested backup/restore. No accelerator control or autonomous corrective-action interface was found.

## Verification performed for this audit

Audit outputs are under `.project-audit` at the workspace root. The environment is separate from the application's managed environment and no saved user data was supplied in this bundle.

| Check | Result |
| --- | --- |
| Outer bundle checksums | 350/350 matched |
| Inner source checksums | 291/291 matched |
| Python syntax parsing | No syntax errors |
| Current full pytest suite | Failed collection on Windows: unavailable `signal.SIGHUP` at `tests/test_security_runtime.py:240` |
| Remaining pytest modules with that module excluded | 1,247 passed, 32 failed, 18 skipped; 1,297 cases in 567.03 seconds |
| Isolated API Test Lab using outer demo fixtures | 32/32 grouped checks passed |
| Four-level smoke workflow/reset | 16/16 named checks passed |
| Real API + Streamlit process startup and HTTP health | Passed with explicit mock/hash/SQLite; both owned processes stopped |
| Source security scanner | Exit 1: nine medium flags; manually reviewed as fixed SQL/URL constructions, no exploitable flow found at flagged lines |
| Current dependency advisory scan | 86 resolved core/UI/dev/pip packages checked; no known advisories, none skipped |
| Focused reproductions of findings | Timing, retrieval, Docker Host rejection, Windows orphan recovery, evidence deletion and bulk-persistence failures reproduced; Windows handoff refusal safely probed |
| Supplemental portable tests from the otherwise uncollectable security module | Audit-only copy: 50 passed, 5 failed, 2 POSIX skips; see note below |
| Real model, normal launcher, Docker, physical facility validation | Not executed |

The audit virtual environment reuses the bundled interpreter's existing site packages where compatible; the exact installed application dependency closure is saved in `.project-audit/dependency-inventory.json` and `resolved-audit-requirements.txt`. `pip check` passed. The advisory result is a dated known-advisory check of this resolved environment, not a guarantee for every version permitted by the broad project requirements.

For supplemental coverage of `test_security_runtime.py`, an audit-only copy changed its project-root constant and used safe `getattr` access for the absent POSIX signal; the original POSIX skip and isolation fixture were retained. This did not repair the source suite. Its five failures were three symlink fixtures blocked by Windows privilege error 1314, one LF/CRLF fixture assumption, and one subprocess mock that also intercepted the launcher's process-identity probe. Details and exact adaptations are in `.project-audit/security-runtime-copy-triage.md`.

The 32 remaining-suite failures are not 32 separate product defects:

| Failure group | Count | Interpretation |
| --- | --- | --- |
| Symlink fixture privilege, Windows path/process assumptions, long temporary paths, Unix-only dependency-layout lookup and duplicated UI fixture identity | 27 | Host/test portability or invalid fixture setup. These do not establish failed product assertions. |
| Unsafe ZIP-name test and the following contaminated case | 2 | Windows ZIP fixture construction rewrote the backslash before upload; its unexpectedly accepted background job contaminated the next test. The drive-path case passed alone. Raw traversal/drive paths remained rejected. |
| Cross-platform archive executable bits | 1 | Reproduced packaging defect described above. |
| Bulk cancellation while waiting for the lifecycle lock | 1 | Reproduced Windows report-persistence race described above; processors remained uncalled. |
| Fresh-project launcher check exceeded 60 seconds | 1 | `--check-packages` stages missing project dependencies before checking, so this fresh-copy test starts installation. Direct read-only validation of the audit environment passed in 17.062 seconds. |

The UI test passed when its two knowledge records received distinct valid draft IDs. Focused package-cache tests with shorter temporary paths passed the two baseline reuse/manifest failures; the remaining link test assumes a Unix package directory before exercising product code. Supplemental focused results do not overwrite the original failures. The exact unmodified results remain in `pytest-portable-results.xml`, `pytest-portable.log` and `test-summary.json`.

Evidence includes `pytest-results.xml`, `pytest.log`, the separately recorded remaining-suite results, `test-lab/test-lab-results.json`, `system-smoke/system-smoke.json`, `runtime-smoke-results.json`, `architecture-reproduction-results.json`, `security_repro_results.json`, `source-security.json`, and `dependency-advisories.json` under `.project-audit`.

One original test invoked a fresh-project installation through `--check-packages`, producing a staged runtime before its 60-second timeout. Those audit-created files and their logs were preserved by non-destructive relocation into `.project-audit/startup-check-side-effects`; the source `.frib` directory is absent again and no related workers remain. Empty data directories created by UI/configuration checks were likewise preserved under `.project-audit/source-created-empty-data`. No downloaded AI model or user evidence was involved. The original 350 outer and 291 inner checksums still matched after the audit.

Automatic approval review rejected deletion of two temporary fixture directories as “blocked by policy,” without a more specific reason. They remain under `.project-audit/bulk-cancel-target-temp` and `.project-audit/bulk-drive-target-temp`. The review was completed with these disposable artifacts retained; no permission change or deletion bypass was used.

Recommended order: repair timing and retrieval correctness, recoverable evidence deletion and Windows bulk recovery/status persistence; fix Windows handoff and portable archive permissions; repair and exercise Docker; align configuration/docs and test portability; then complete real-model/host acceptance and domain-expert validation.
