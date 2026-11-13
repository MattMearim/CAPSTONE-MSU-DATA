# Reset saved application data

The reset starts the running application again with no saved datasets, reference procedures or reviewed knowledge. It is a permanent deletion of the active workspace's saved content. Export anything you want to retain first, or stop FRIB and back up its complete data directory.

## Use the dashboard

1. Expand **Reset project data** in the sidebar on any page. Review the current saved-data counts before continuing. **Refresh data counts** retries an unavailable count check.
2. Select **I understand that this permanently deletes the project data listed above.**, enter **RESET** in **Type RESET to confirm**, and press **Reset project data**. The button requires both exact confirmations and readable saved-data counts.
3. Wait for the success message and **Reset receipt**. The dashboard returns to Home; saved-data counts should then be zero, except for **one audit entry** identifying the reset. The active browser session's old event, answer, draft, preview, uploaded-file and download state is cleared.
4. Refresh other open FRIB browser sessions, then generate or import a new dataset. Existing sample files remain available, but no examples or procedures are automatically seeded into storage.

The action affects the application's active data directory only. The usual directory is `data` in the project; `start.py --local-ai` normally uses `data-local-ai`. `FRIB_DATA_DIR` can choose another directory. Resetting one does not reset the others. Downloaded exports, backups, presentation evidence and files elsewhere on your computer are outside this reset.

## What is deleted and retained

| Deleted saved content | Included details |
|---|---|
| Datasets and event evidence | Numeric samples, categories/states, logs, metadata, source event JSON, upload originals, evidence attachments and reviewed import copies/repair receipts. |
| Derived investigation records | Analysis results/features/plot data, draft reports, review decisions and published engineering knowledge. |
| Reference procedures | Approved and unapproved library documents, original uploaded bytes, metadata, approved passages and their retrieval vectors. |
| Previous audit history | Creation, import, deletion and human-review entries, including historical draft snapshots. |
| Orphaned app-owned stored files/index rows | Leftover event/document files, active retrieval rows without a catalog entry, and inactive index files under the application's validated retrieval directory. |

| Retained | Reason / location |
|---|---|
| Source code, launchers and Python environment | The application stays installed and runnable. |
| YAML configuration, prompts and provider settings | Reset clears content; it does not switch model or embedding providers. |
| Embedding fingerprint / storage schema | Keeps the empty index consistent with the running configuration. |
| Application log files | Logs remain available for troubleshooting. |
| Bundled `sample_data` and `sample_docs` | Files remain available for explicit import or deliberate demo seeding. Fictional procedures are not automatically approved. |
| One minimal reset audit receipt | Reset ID, time and removal counts; old evidence or draft content is not retained in this receipt. |

The data directory itself and empty database/index files can remain after reset. An empty content catalog does not require an empty directory. Reset is separate from uninstalling the application or removing a downloaded model.

## Confirm the result

The read-only status endpoint is:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/system/data
```

It returns `counts` for events, analyses, drafts, reviews, knowledge, documents, document_chunks, event_files, audit_entries, stored_files, legacy_index_files and retrieval_vectors, plus `reset_pending`. `stored_files` includes inactive index files; `legacy_index_files` identifies that subset. A completed reset has `reset_pending: false`, all content/file/vector counts zero, and `audit_entries: 1`.

The advanced API operation is `POST /system/reset` with JSON:

```json
{"confirmation":"RESET"}
```

This is the destructive operation; checking `/system/data` does not perform it. A successful response includes `reset: true`, `reset_id`, `removed` and `remaining` counts. Use the API documentation at `http://127.0.0.1:8000/docs` to inspect its schema. With alternate launcher ports, use the configured API port instead of 8000.

After reset, **Dataset library**, **Files & Documents** and **Engineering Wiki** should be empty. Previously saved event/document download IDs should be unavailable. The assistant should have no old approved source excerpts to retrieve. A newly generated dataset, analysis and newly uploaded procedure should work normally; a restart should keep the old workspace content absent.

## Interrupted reset

Reset records that cleanup is pending before deleting content. If a file lock, permissions problem or index failure interrupts it, the application must not report success. Content endpoints are unavailable while reset is pending so old data is not exposed or repopulated during recovery. Fix the reported filesystem/index problem and retry the explicitly confirmed reset, or restart to let startup resume pending cleanup.

Use `/system/data` to inspect `reset_pending`. Do not treat a partially completed attempt as a fresh workspace. The reset operates on bounded application-owned event/document directories; unsafe links or paths are rejected instead of following them into unrelated files. Close external scripts that write directly into the same storage before resetting.

A custom SQLite retrieval-index path outside `<FRIB_DATA_DIR>/chroma` (normally `data/chroma`) is also refused before deletion. Reset does not clear an external/shared index file. Use an application-owned index path for this workflow; a safety refusal leaves existing content unchanged.

## Run the isolated tests

Complete setup with **Start FRIB.cmd**, then copy **Active interpreter** from **System & upgrades → Hardware details** and stop FRIB before installing development packages. From the project root, replace the placeholder with that exact path. A retained `.venv` may be inactive after an upgrade; refresh the path after further upgrades. These tests use temporary storage and deterministic providers; they do not reset the application's user data.

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest tests/test_reset.py -q
& $fribPython -m pytest tests/test_reset_ui.py -q
& $fribPython -m pytest tests/test_api_lifecycle.py tests/test_mixed_api.py tests/test_quality_api.py tests/test_review_gate.py tests/test_dashboard_ui.py -q
& $fribPython -m pytest -q
& $fribPython scripts/run_system_smoke.py --output reset_evidence
```

The focused reset tests should verify confirmation rejection without mutation; complete removal including originals, derived records, audit snapshots and vectors; preservation of configuration/logs/samples; interrupted-reset recovery and unsafe-path rejection; empty state across restart; and a working generation/import/analysis/document/review lifecycle afterward. UI tests verify explicit acknowledgement/typing, failure visibility and stale-session-state clearing. Inspect the actual pytest output for execution results; this guide does not assume a fixed test count.

Concrete reset assertions are in `tests/test_reset.py`:

| Behavior | Exact pytest function |
|---|---|
| Invalid confirmation has no side effects | `test_reset_requires_exact_explicit_confirmation_without_side_effects` |
| All levels, originals, orphan files, vectors and old audits removed; retained files unchanged | `test_reset_removes_all_levels_orphan_files_vectors_and_old_audits` |
| Fresh four-level workflow and persistence after reset | `test_four_level_lifecycle_still_works_after_reset_and_restart` |
| Failure is visible; explicit retry or startup resumes cleanup | `test_failed_cleanup_is_not_successful_and_resumes_before_retrieval` |
| Unsafe filesystem targets leave catalog/files untouched | `test_reparse_point_is_rejected_before_catalog_or_files_are_deleted`; `test_redirected_event_root_is_refused_before_mutation`; `test_redirected_sqlite_index_is_refused_before_any_data_mutation` |
| In-flight requests cannot restore content after reset | `test_inflight_upload_finishes_before_reset_and_cannot_restore_content` |
| Cached workers and provider switches cannot restore old retrieval | `test_cached_second_worker_drops_stale_memory_retrieval_after_reset`; `test_switching_to_memory_reset_clears_inactive_sqlite_and_cannot_resurrect` |
| Chroma collection cleanup/batches | `test_chroma_clear_removes_orphan_entries_in_batches_without_model_dependency` |

The integrated reset fixture uses SQLite and memory vector providers. The Chroma cleanup assertion uses a fake client; it does not validate an installed Chroma service/version. `tests/test_reset_ui.py` uses Streamlit AppTest with a fake API for confirmation controls, success/error state, upload-widget identities and cache clearing; it is separate from real-browser visual inspection.

The smoke runner uses isolated temporary storage and writes `reset_evidence/system-smoke.json` plus `SYSTEM_SMOKE.md`. It exercises all four levels, the reset confirmation guard, populated reset, unavailable former originals, empty retrieval, restart, a fresh complete workflow and a second reset. Inspect its recorded checks and exit status; it does not reset your active FRIB workspace.

The broader suite also exercises CSV/text/PDF ingestion, unit conversion, quality/repair gates, domain processing, approved-only retrieval, human review, persistence, downloads and individual deletion. It does not establish live FRIB connectivity, real-model answer quality or Docker deployment on an untested host.
