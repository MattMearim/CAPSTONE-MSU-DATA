# Startup and upgrades validation — October 12, 2026

The Windows launcher and the new **System & upgrades** page are implemented. Double-click **Start FRIB.cmd** in an extracted project, or **START_FRIB.cmd** in the existing outer workspace. The launcher checks Python, required package versions and imports, and dependency consistency before starting the API and dashboard. It installs missing requirements in a private, staged environment.

## Final results

| Verification | Result |
| --- | --- |
| Complete pytest suite, rerun after final demo packaging fixes | **670 passed, 1 skipped, 0 failures** in 206.37 seconds |
| Dashboard and maintenance UI tests with freshly installed dependencies | **31 passed** |
| Fictional Test Lab through real APIs on the fresh installation | **32/32 grouped checks passed** |
| Four-level workflow and reset checks in disposable storage on the fresh installation | **16/16 checks passed** |
| Real Windows launcher maintenance scenarios | **5/5 passed** |
| Running maintenance API queue, inventory and cancellation | Passed |
| Explicit official PyPI version lookup | **15/15 package lookups succeeded** |
| Original workspace preservation | Record counts unchanged; no pending upgrade left behind |
| Existing browser visual check | System page, hardware cards, latest releases and per-package update choices rendered correctly |

The skipped test requires creating a directory symlink, which this Windows account cannot do. Two warnings came from external Starlette/HTTPX/AnyIO deprecations; no application test failed.

## Real first-run verification

A source-only ZIP was extracted into a deep Windows folder containing spaces. It had no `.venv`, managed environment or private Python. The actual **Start FRIB.cmd** entry point was run with private-runtime bootstrap forced, so an already installed system Python could not hide a missing-runtime problem.

The launcher downloaded and verified official Python **3.13.16 x64**, extracted it, created the environment, installed the required project/UI dependencies and the Test Lab runner dependency, validated imports and `pip check`, and ran all 32 Test Lab checks successfully. Windows had `LongPathsEnabled=0`; no registry or machine-wide PATH change was needed.

The freshly resolved stack included FastAPI 0.143.0, Uvicorn 0.54.0, Pydantic 2.14.1, NumPy 2.5.4, pandas 3.0.6, SciPy 1.18.1, Streamlit 1.65.0, Plotly 7.1.0 and pypdf 6.20.0. These are the releases actually installed during this verification, not fixed promises about future package-index contents.

Real first-run testing caught and fixed inherited PowerShell module-path issues, Windows archive/venv long-path failures, and an obsolete standalone `colorama` import check. Regression tests cover the corrections.

## Real maintenance verification

All maintenance mutations used the disposable extracted copy:

1. Healthy startup succeeded with package indexes disabled and an unreachable network proxy. The active pointer and package-install log were unchanged.
2. A queued Python, pip and pypdf update built and validated a replacement environment, changed the active pointer atomically, consumed its plan and retained the old environment. The non-core HTTPX runner dependency survived.
3. A deliberately offline queued update failed during installation. The previous validated environment stayed active, the failure receipt and queue remained available, and startup still succeeded using the previous environment.
4. Cancelling the failed plan allowed a normal subsequent offline startup.
5. Hashes of configuration and a disposable evidence sentinel stayed identical through successful and failed updates.

The running API also accepted a selected-package plan, exposed it in system inventory, cancelled it, and completed all 15 explicit version lookups. The main application remains running at `http://127.0.0.1:8501/` with no queued upgrade and unchanged saved-record counts.

## Functional coverage and limits

The full suite covers ingestion, provenance and original-file downloads; corruption detection and explicit repairs; unit detection/conversion; missing samples and quality rules; RF, mechanical and PLC processing; labeled plot specifications; procedure upload, revision approval and deletion; citation-backed retrieval; human approve/correct/escalate decisions; reviewed knowledge; persistence; file removal; guarded reset; and reuse after reset. The fresh-install Test Lab and smoke runner exercised those flows again through APIs with disposable data.

This is validation of the local prototype in **mock/hash/SQLite mode** on Windows 11 x64. Physical ARM64 machines, Docker deployment, real accelerator controls, downloaded semantic models and Ollama model inference were not exercised. Hardware recommendations are estimates. Browser permission prevented opening the additional disposable browser instance; fresh-dependency UI behavior was checked with 31 automated UI tests, and the existing main browser tab was inspected visually. A requested narrow viewport override did not change this browser's reported viewport, so no new mobile-browser result is claimed.

## Reproduce

- Run **Start FRIB.cmd --check** to validate startup without launching services.
- Run **Run Test Lab.cmd** for the 32 grouped checks without touching saved workspace data.
- Follow [SYSTEM_AND_UPGRADES.md](SYSTEM_AND_UPGRADES.md) for per-component updates, active interpreter selection, recovery and developer checks.

The outer workspace's `deliverables/Startup_And_Upgrades` folder contains JUnit XML, first-run and maintenance logs, Test Lab/smoke reports, JSON inventory, before/after workspace snapshots and screenshots. The portable source ZIP excludes runtime environments, downloaded packages and saved evidence.
