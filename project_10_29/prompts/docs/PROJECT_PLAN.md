# Project status and remaining validation

The local capstone prototype implements the four-level workflow. Start it with **Start FRIB.cmd**; see [README.md](../README.md) for setup and [the requirements matrix](REQUIREMENTS_MATRIX.md) for a feature-by-feature assessment. Completion of the prototype does not mean the system is commissioned for FRIB operations.

## Completed prototype work

| Area | Implemented |
|---|---|
| Contracts and generation | Event, analysis, retrieval, draft and review contracts; generated JSON Schemas/OpenAPI; configurable RF, mechanical and PLC generators; seeded reproducibility and portable generation CLI |
| Level 1: preserved evidence | Canonical event JSON, provenance/context metadata, original CSV/JSON uploads, evidence attachments, SHA-256, immutable originals, duplicate-ID rejection and persistent catalogs |
| Level 2: engineering views | Timestamp alignment and processing notes, RF trip features and power comparison, mechanical RMS/FFT, PLC timelines/sequence checks, optional descriptive X-ray/gradient trends, charts and machine-readable exports |
| Level 3: approved references | PDF/TXT/Markdown originals, approval filtering, versions/pages/chunk IDs, persistent retrieval, extractive demo mode, local-model adapters, citation checks and embedding-index compatibility checks |
| Level 4: human decision gate | Structured drafts, tentative hypotheses, editable corrections, named reviewer/acknowledgement, Approve/Correct/Escalate, persisted review status, duplicate-publication prevention and audit snapshots |
| User workflow | Nine dashboard pages, multiple file uploads, original downloads, confirmed deletion, reviewed knowledge search and report downloads |
| Startup and developer validation | One-click bootstrap/launcher, readiness checks, logs and cleanup; automated API/UI/storage/numerical tests; Windows startup/browser checks; Docker configuration supplied |

The default demonstration needs no AI service or model download. Bundled procedures are fictional and must remain labeled as demonstration material. Files, records and indexes persist in the selected data directory.

## Sponsor and facility work remaining

1. Obtain official approved procedures and representative facility captures, including calibrated units, real RF/SRF trips and field-emission/conditioning scans.
2. Implement and authorize read-only adapters for EPICS, archives, LLRF, cryogenic systems and electronic logs. File ingestion is the current adapter boundary; it is not live facility acquisition.
3. Review synthetic physics, domain hypothesis rules, numerical tolerances and failure cases with subject-matter experts. Descriptive field-emission plots do not validate causal or conditioning-effect conclusions.
4. Build an expert-scored retrieval/answer evaluation set. Evaluate optional models for faithfulness, relevance, unsupported conclusions, latency and reproducibility.
5. Define authentication, roles, document approval/governance, retention, backup/restore policy and host/network security before operational deployment.
6. Verify clean first-time installation and Docker build/run on the intended deployment host. Docker configuration is included; Docker execution was unavailable in the development environment.
7. Prepare the final sponsor report and presentation using the exported contracts, requirements matrix, validation evidence and a rehearsed demo. Include unresolved limitations explicitly.

Use [VALIDATION_PLAN.md](VALIDATION_PLAN.md) to record acceptance results and [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the demonstration sequence. No stage authorizes autonomous corrective actions or accelerator control.
