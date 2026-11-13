# Validation plan

## Automated software checks

Complete first setup with **Start FRIB.cmd**. In **System & upgrades → Hardware details**, copy **Active interpreter**, then stop FRIB before installing development packages. From the project folder, replace the placeholder with that exact path and run in PowerShell. Refresh the path after a managed upgrade; a retained `.venv` may no longer be active.

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest -q
```

Tests use temporary databases/originals. They must not use the real `data` directory for destructive checks.

- **Contracts and generation:** reject unsafe IDs, duplicate signal names, invalid lengths/timestamps/nonfinite values, invalid corrections and unbounded generator requests. Confirm seeded signal reproducibility across three domains.
- **Processing:** compare against known RF timing/decay, mechanical frequency/RMS, sine amplitude/frequency and PLC chronology. Test differing sample grids, missing signals, short/partial captures and JSON-finite missing estimates. Confirm original events are unchanged.
- **Documents:** exact original bytes and SHA, readable PDF/TXT/MD, malformed/empty/oversized upload rejection, approval exclusion, SQLite and memory persistence, delete/restart and interrupted index cleanup.
- **Events/evidence:** duplicate ID conflict, original JSON/long CSV exports, exact attachment bytes, individual attachment deletion and full event deletion cascade.
- **RAG:** approved sources and versions, no unrelated explicit-domain fallback, extractive demo content, valid citations, offline/uncited model answers not flagged as grounded generation.
- **Mixed ingestion:** CSV measurement/category/text roles, per-row and explicit cell units, malformed/unknown/incompatible rejection, ISO/relative/ordinal timing, PDF/text extraction, exact originals and atomic imports.
- **Unit conversion:** finite quantities, compatible dimensions, SI prefix case, temperature offsets, temperature differences, source provenance and standardized exports.
- **L1 quality and repairs:** damaged row shapes/quotes/encoding, duplicate headers/records, missing tokens/cells, mixed text and numeric fields, unsupported/incompatible/mixed unit scales, manual unit candidates and complete-file limits. Explicit repairs must preserve exact originals, produce checksummed receipts, retain untouched text and reject arbitrary filling/unit guesses.
- **L2 quality:** declared versus estimated cadence, single missing records, interval locations, irregular timing, flatline/spike/step behavior, stable-value tolerances, bounds, channel coverage, absent/misspelled required channels, state chatter and finite JSON with extreme values. Domain analysis must not interpolate through flagged recording gaps.
- **Quality UI and portability:** original versus reviewed-copy row labels, accepted sample positions, explicit repair selection and invalid-selection guards, report search/filter/download, canonical SI expectations, full-data gap breaks and sampled previews. Repeat repair→preview→import→original download from an extracted ZIP.
- **Dynamic UI:** live mapping previews, explicit save, editable plot labels, separate unit axes, channel/window/category/severity filters, original versus standardized download labels.
- **Draft hypotheses:** integrate deterministic RF/mechanical/PLC observation-pattern candidates, verify consecutive ranks and ordering changes with supporting/contradictory measurements, retain actual findings and ranking limitations, skip missing/nonfinite/nonnumeric features, and confirm synthetic ground-truth labels never influence candidates or enter model prompts. Evidence ordering is not statistical confidence or causal diagnosis.
- **Human review:** Approve/Correct/Escalate, retained evidence snapshots and original/final audit, persisted review status and repeated stale submission rejection.
- **UI:** navigation, file uploads/confirmed deletion, provenance import, structured corrections, named reviewer/acknowledgement, disabled repeated submission, all derived chart types and readable API validation errors.
- **Installation and upgrades:** clean-copy Windows bootstrap without using existing Python; trusted runtime archive and executable signature verification; required versions/imports and dependency checks; warm offline launch; staged activation and failure recovery; concurrent-start locks; allowlisted per-package/runtime plans; optional dependency preservation; queue/cancel/status UI; public metadata timeout/size handling; hardware tiers with unknown/limited resources.

## Local launch and browser acceptance

1. Run `& '.\Start FRIB.cmd' --check` from PowerShell. Startup validates dependency versions, imports and consistency; it does not run the full functional suite.
2. Start with `& '.\Start FRIB.cmd' --no-browser`. Verify backend readiness and Streamlit health before the ready message.
3. Open http://127.0.0.1:8501. Inspect readable light-theme navigation, demo banner and the full workflow.
4. Use temporary disposable datasets to try generation -> analysis -> draft -> review -> wiki. Upload a fictional document and an evidence file; verify source IDs, original downloads and checksums.
5. Restart and confirm data and draft status persist. Delete only disposable examples through confirmed controls, restart again and confirm they remain absent.
6. Press Ctrl+C in the launcher. Confirm both owned services stop and their ports are available.
7. Start with an occupied port and confirm a readable explanation without disturbing another service.

## Checks requiring a separate environment or sponsor

- Build/run Docker Compose on the intended host and repeat persistence/readiness tests.
- Enable Ollama/LM Studio plus semantic embeddings in a separate data directory; evaluate correct citations, hallucinations, failure handling, latency and reproducibility with expert-reviewed questions.
- Test real read-only acquisition adapters and document approval identity/roles.
- Agree calibrated units, physics models, processing tolerances, field-emission scan comparisons and hypothesis-ranking criteria with FRIB experts.
- Assess security, concurrency at intended load, retention and backup/restore before shared deployment.

Synthetic software tests alone do not commission a facility decision-support system.
