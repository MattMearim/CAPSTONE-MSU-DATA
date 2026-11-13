# Validation report

Validated on 2026-10-11 on Windows with Python 3.13.0, using the project's private environment. `requirements-tested.txt` records its direct dependency versions. Default providers were mock generation, hash embeddings and persistent SQLite retrieval.

## Results

| Check | Result |
|---|---|
| Complete automated suite, including extracted-distribution workflow | **440 passed in 58.60 seconds** |
| Additional final plot overflow regression | **1 passed in 1.08 seconds** |
| Total distinct automated cases validated | **441 passed** |
| Windows one-command startup | API and dashboard readiness succeeded at ports 8000 and 8501 |
| Ctrl+C shutdown | Both services stopped without a traceback; both ports became available |
| Source portability | Extracted source imported from its own `src`, loaded its own configuration/prompts and used isolated fresh data |
| Source archive | CRC and per-file SHA-256 verification; source manifest included |
| Contracts | JSON schemas and OpenAPI regenerated from current models/API |

The full-suite warnings were two third-party deprecations involving Starlette/httpx TestClient and AnyIO's BlockingPortal alias. They did not cause failures.

## What was exercised

- Reproducible RF, mechanical and PLC generation; parameter validation; standalone generation without AI startup.
- Timestamp alignment, cleaning provenance, FFT scaling and bandwidth, event-window features, pressure/power comparisons, state chronology and optional X-ray/gradient summaries.
- Immutable stored originals, byte-level hashes, JSON/CSV downloads, attachment upload/download/delete, document approval/indexing/download/delete and event cascade deletion.
- Persistence and restart with SQLite and memory retrieval backends, interrupted deletion recovery and embedding-identity checks.
- Approved-source filtering, source/version references, extractive demo answers and unavailable/uncited model behavior.
- Tentative evidence-pattern ordering, missing/nonfinite inputs, synthetic-ground-truth exclusion, preserved observations and evidence snapshots.
- Human approval, correction, escalation, audit snapshots, stale/concurrent review rejection and publication boundaries.
- Mixed CSV, text/log and selectable-text PDF ingestion; numeric, category, boolean and operator-note mappings; content summaries and descriptive analysis without inferred physical diagnoses.
- Per-cell and per-row units, time units, SI normalization, affine temperature conversion, temperature differences, strict unit compatibility, preserved conversion provenance and unknown-unit handling.
- Bounded previews that validate the full upload, invalid values outside the preview window, atomic import failures, duplicate protection and preserved original upload bytes.
- L1 malformed shapes/quotes/encoding, duplicate headers/records, missing cells and tokens, invalid/nonfinite quantities, possible sentinel values, unit candidates and timestamp consistency.
- Explicit duplicate removal, selected malformed-row exclusion, recognized missing-token and selected invalid-cell marking, stable time sorting, refusal of arbitrary edits/filling/unit guesses, exact repair receipts and separate original/derived attachments.
- L2 declared versus estimated recording cadence, single missing records, bounded gap intervals, sample-rate mismatches, irregular timing, flatlines, spikes, sustained changes and boundary jumps, SI bounds/stability tolerances, required/misspelled channels, capture coverage and possible categorical chatter.
- Domain-analysis fallback across missing/irregular timing or numeric overflow, finite JSON results, and unchanged source evidence even for extreme finite values.
- Original versus reviewed-copy row labels, accepted sample positions, optional repair selection with invalid-selection guards, quality search/severity/download controls, full-capture line breaks beyond the report's 25 location examples, marker-only sampled previews, and ordinal timing guards.
- Interactive plot titles, channel labels and units, time windows, state/category views, severity filters, original and standardized downloads, and the built-in unit converter using UI component tests.
- Streamlit pages and forms, file controls, corrections, source separation, loading states and friendly validation errors.
- Launcher/configuration behavior from another working directory.

The distribution test creates and extracts a source ZIP, imports the bundled JSON examples for all three domains plus the mixed-unit CSV and operator shift log, verifies standardized pressure/temperature values and retained states/logs, and exercises the deliberately damaged quality-review CSV through original blocking findings, explicit repairs, preview, import, cadence/stability warnings and an exact original-file download. It also analyzes captures, creates and approves drafts, uploads and downloads a reference and an evidence file, checks retrieval, deletes the files, reconstructs services, checks persistence and deleted-source exclusion, then deletes only its temporary events. It uses the already-installed dependencies; it does not rely on the original project's runtime records.

## Practical limits

Earlier browser inspection confirmed readable dashboard pages after the light-theme correction. The browser tool blocked the final visual recheck, so the final check relies on UI component tests and live service readiness. A fresh dependency installation on a clean computer, Docker execution, optional Ollama/LM Studio/semantic embedding operation and real-model answer quality were not exercised in this environment.

Scanned PDFs and images require a separate OCR step. Text ingestion retains observations, explicit states and severity labels; it does not establish physical causality. Missing measured timestamps use clearly labeled record order and disable analyses that depend on elapsed time. Unknown physical units require correction before mixed-file normalization; legacy records retain unknown units with visible warnings.

Quality detection is deterministic and heuristic. A recording or value change can be legitimate; flags do not establish negligence or physical sample loss. Cadence, stability and range expectations require the correct acquisition plan and calibrated units. The report retains total counts with bounded location examples, and missing observations are never reconstructed. See `DATA_QUALITY_GUIDE.md` for assumptions and review steps.

This validates a working capstone prototype with synthetic data. It does not establish physical diagnosis accuracy, statistical hypothesis confidence, field-emission conditioning effectiveness or readiness for facility operation. Live read-only FRIB connectors, official approved procedures, calibrated physical models/tolerances, expert evaluation, identity/roles and operational backup/retention/deployment requirements remain sponsor validation work. See `REQUIREMENTS_MATRIX.md` and `VALIDATION_PLAN.md`.

## Reproduce

For a new run, complete setup with **Start FRIB.cmd**, then copy **Active interpreter** from **System & upgrades → Hardware details** and stop FRIB before installing development packages. From the project folder, replace the placeholder with that exact path. A retained `.venv` may be inactive after an upgrade; refresh the path after further upgrades. These commands reproduce checks; the execution findings above remain the record of the original run.

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest -q
& '.\Start FRIB.cmd' --check
& '.\Start FRIB.cmd' --no-browser
```

Press Ctrl+C after the launcher reports readiness. Tests operate on temporary data. Rebuild and verify a distribution with `& $fribPython scripts/package_project.py <output.zip>`, replacing the output placeholder with a destination path.
