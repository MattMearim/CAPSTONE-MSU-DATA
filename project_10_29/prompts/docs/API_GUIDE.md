# API and file lifecycle

Interactive endpoint/schema documentation is available at http://127.0.0.1:8000/docs when FRIB runs. `docs/openapi.json` and `contracts/*.schema.json` are exported snapshots.

| Operation | Endpoint |
|---|---|
| Health/providers/domains | GET /health |
| Generator names/defaults | GET /generators |
| Unit catalog / compatible conversion | GET /units; POST /units/convert |
| L1 source quality / explicit repair review | POST /ingestion/quality (multipart file, optional options JSON) |
| Inspect / validate mixed file without saving | POST /ingestion/preview (multipart file, optional options JSON, validate=true) |
| Import mixed CSV / narrative evidence | POST /ingestion/import (multipart file, options JSON) |
| Generate domain / custom settings | POST /events/generate; POST /events/generate-custom |
| Import/list/get/delete events | POST /events; GET /events; GET or DELETE /events/{event_id} |
| Original JSON / standardized JSON / long CSV | GET /events/{event_id}/download?format=json, normalized-json or csv |
| Analyze / saved result | POST /events/{event_id}/analyze; GET /events/{event_id}/analysis |
| Read-only L2 quality review | POST /events/{event_id}/quality (JSON expectations) |
| Evidence attachment upload/list | POST or GET /events/{event_id}/files |
| Original evidence file / delete | GET /events/{event_id}/files/{file_id}/download; DELETE /events/{event_id}/files/{file_id} |
| Upload original reference | POST /documents/index (multipart file, approved=false by default, title, version) |
| List/download/delete references | GET /documents; GET /documents/{document_id}/download; DELETE /documents/{document_id} |
| Retrieve approved context | POST /rag/query (question, optional event_id) |
| Create/reopen draft | POST or GET /events/{event_id}/draft |
| Inspect specific draft | GET /drafts/{draft_id} |
| Explicit human review | POST /drafts/{draft_id}/review |
| Reviewed knowledge | GET /knowledge; GET /knowledge/search?q=... |
| Persistent audit history | GET /audit |

Event creation rejects existing IDs with HTTP 409. Uploads are bounded to 20 MiB, with safe filenames and supported types. Invalid content receives a readable 400/422; oversized uploads receive 413. Original references are PDF, TXT or MD. Evidence attachments also accept CSV, JSON, logs, PNG and JPEG.

Unapproved reference uploads are retained with `indexed_chunks=0`; they never enter assistant retrieval. To change an unapproved document to approved, upload the original again with approval explicitly selected and remove the earlier unapproved copy if unnecessary. Previous versions remain independently auditable unless deliberately deleted.

The event CSV download is long format (`kind,name,timestamp_s,value,unit,level,source,message`), retaining each signal's actual time axis and state/log evidence while standardizing compatible numeric units. The interactive CSV importer accepts wide mixed numeric/category/log columns. Use standardized JSON to export the structured normalized view, original JSON to download the pre-standardization event, and the evidence-file download to obtain exact uploaded bytes.

## Mixed ingestion

`POST /ingestion/preview` inspects file content without saving an event. Set form field `validate=true` to apply the supplied options and receive `validation: {valid, errors}`, `event`, `summary`, `quality: {l1, original_l1, l2}`, a repair receipt when applicable and optional `preview_notice`. Preview sampling is a presentation limit; the entire source is parsed and reviewed. Damaged source content receives an actionable quality report and `validation.valid=false`; invalid settings and unsupported repairs return HTTP 400.

`POST /ingestion/import` accepts the same multipart file and an `options` JSON string. It returns `{event, summary, original_file, derived_file, quality, repair_receipt}`. Options include `event_id`, `domain`, `dataset_name`, `metadata`, `imported_by`, `time_column`, `time_unit`, `column_roles`, `signal_names`, `source_units`, `target_units`, `unit_columns`, `invalid_rows`, `_repairs` and `quality_expectations`. Roles are `numeric`, `category`, `log` and `ignore`. The public application stores recognized quantities in canonical SI even if a parser target unit was supplied. Original uploaded bytes are attached automatically and checksum verified. Explicit repairs add a separate derived CSV attachment and provenance receipt. Validation completes before persistence; duplicate IDs return 409.

## Quality options

`POST /ingestion/quality` returns an L1 report without saving anything, including readable findings for structurally damaged CSVs. Reports contain `stage`, `status` (`ok`, `review`, `blocked`), severity counts, bounded affected-row/time examples, suggestions and unit candidates. Unit candidates have `requires_confirmation=true` and `assigned=false`; they never change measurements.

`options._repairs` is a list of explicitly selected operations, for example `[{"operation":"drop_exact_duplicate_rows"}]`. Offered repair objects may include physical `rows` and exact column names in `columns`. Supported operations are `drop_exact_duplicate_rows`, `sort_by_time`, `mark_missing_tokens`, `drop_malformed_rows` (selected rows required) and `drop_invalid_numeric_cells` (selected numeric cells required). The alias `action` is accepted for `operation`. Unknown or conflicting operations are rejected. No fill or interpolation operation is provided. The same options apply repairs before preview inspection and before import; the raw upload stays unchanged.

`quality_expectations` accepts `expected_interval_s`, `gap_factor`, `required_channels`, and a `channels` mapping. Each channel may specify `expected_interval_s`, `expected_stable`, `stability_tolerance`, `min`, `max`, and `flatline_samples`. Numeric thresholds refer to stored units after SI normalization. Settings are strict, finite and range checked. Example: `{"expected_interval_s":1,"channels":{"pressure":{"expected_stable":true,"stability_tolerance":100,"min":0,"max":2000}}}`.

`POST /events/{event_id}/quality` accepts `{"expectations": {...}}` and returns a fresh L2 report without editing the event. `POST /events/{event_id}/analyze` accepts the same optional JSON body; otherwise it uses import-time expectations. Its `features.data_quality` records the applied checks. Missing or irregular timing causes a descriptive fallback instead of domain interpolation/spectra.

CSV and narrative imports are bounded and preserve category/text source references. TXT/MD/LOG/PDF evidence becomes recorded logs and explicit categorical assignments, with descriptive summaries. Missing timing uses labeled `row_index` coordinates; domain rates/durations/FFT are not calculated from row order. See `INGESTION_GUIDE.md` for examples.

`POST /units/convert` takes `{value, from_unit, to_unit}` and returns those normalized fields plus `converted_value` and `dimension`. Conversion checks finite values, exact prefix case, compatibility and temperature offsets. Absolute and difference temperatures are separate dimensions. Unknown nonlinear scales are not guessed.

A review is atomic and only accepts a stored draft whose status is `draft`. A correction includes the corrected draft; the server preserves identifiers, original generation time and evidence snapshot. Every completed review retains both original/final drafts in the audit. A fresh draft is required for a subsequent review.

Deleting a dataset removes its files, analysis, drafts, reviews and knowledge; audit records remain. Deleting a reference removes it from future retrieval. Historical report snapshots still identify sources used when a report was generated.
