"""ZIP collections with bounded uploads and fragment-only job progress."""
from __future__ import annotations

from html import escape
import json
from pathlib import PurePosixPath
import re
import time

import streamlit as st

from frib_ds.dashboard.reset_ui import upload_widget_key
from frib_ds.dashboard.design import section_header
from frib_ds.dashboard.busy_ui import render_run_animation, _progress_style

TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
JOB_ID = re.compile(r"BULK-[a-f0-9]{32}\Z")
DEFAULT_LIMITS = {"max_files": 1000, "max_total_bytes": 1024 ** 3, "max_file_bytes": 20 * 1024 ** 2}


def size_label(value):
    value = max(0, int(value or 0))
    return f"{value / 1024 ** 3:.2g} GiB" if value >= 1024 ** 3 else f"{value / 1024 ** 2:.1f} MiB" if value >= 1024 ** 2 else f"{value / 1024:.1f} KiB"


def upload_size(upload):
    if isinstance(getattr(upload, "size", None), int):
        return upload.size
    position = upload.tell()
    upload.seek(0, 2)
    size = upload.tell()
    upload.seek(position)
    return size


def validate_selection(uploads, limits):
    if len(uploads) != 1 or PurePosixPath(uploads[0].name).suffix.lower() != ".zip":
        raise ValueError("Choose one ZIP archive. In Finder, right-click your folder and choose Compress first.")
    total = sum(upload_size(item) for item in uploads)
    if total > limits["max_total_bytes"]:
        raise ValueError(f"This batch exceeds {size_label(limits['max_total_bytes'])}. Split it into smaller batches.")
    for upload in uploads:
        limit = limits["max_total_bytes"] if PurePosixPath(upload.name).suffix.lower() == ".zip" else limits["max_file_bytes"]
        if upload_size(upload) > limit:
            raise ValueError(f"{upload.name}: exceeds the {size_label(limit)} per-file limit. Split large measurement captures into smaller files.")
    return total


def parse_options(text):
    if len(text) > 32_768:
        raise ValueError("Shared import settings are too long.")
    value = json.loads(text or "{}")
    if not isinstance(value, dict):
        raise ValueError("Shared settings must be a JSON object.")
    if {"event_id", "dataset_name", "approved"} & set(value):
        raise ValueError("Shared settings cannot override event IDs, per-file dataset names or document approvals.")
    return value


def _read_report(job_id, api_get):
    if not JOB_ID.fullmatch(str(job_id)):
        raise ValueError("The stored import job identifier is invalid. Start a new batch.")
    report = api_get(f"/ingestion/bulk/{job_id}")
    if not isinstance(report, dict) or report.get("job_id") != job_id or not isinstance(report.get("files"), list):
        raise ValueError("The import service returned an unreadable progress report.")
    return report


def _render_progress(job_id, api_get, api_post, friendly_error, navigate_event):
    previous = st.session_state.get("bulk_report", {})
    active = previous.get("status") not in TERMINAL
    try:
        report = _read_report(job_id, api_get) if active else previous
        st.session_state["bulk_report"] = report
    except Exception as exc:
        st.error("Import progress is unavailable. " + friendly_error(exc))
        if st.button("Retry import progress", key="bulk_retry_progress"):
            st.rerun()
        return
    if active and report.get("status") in TERMINAL:
        # Stop the timer when the worker finishes, rather than keep polling an
        # idle dashboard or re-rendering the entire application every two seconds.
        st.rerun(scope="app")
    status = report.get("status", "queued")
    processed, total = int(report.get("processed_files", 0)), int(report.get("total_files", 0))
    counts = report.get("counts") or {}
    percentage = min(100, max(0, int(processed / total * 100))) if total else 0
    _progress_style()
    with st.container(key="bulk_progress"):
        if status not in TERMINAL:
            render_run_animation("running", "Importing your collection")
        elif status == "completed" and not counts.get("failed"):
            render_run_animation("success", "Import finished")
        elif status == "failed":
            render_run_animation("failed", "Import needs attention")
        st.progress(percentage, text=f"{percentage}% · {status.replace('_', ' ').capitalize()} · {processed:,} of {total:,} files processed")
        st.caption("Percentage counts files processed; file sizes and processing times can differ.")
    imported, failed, skipped = st.columns(3)
    imported.metric("Imported", counts.get("imported", 0))
    failed.metric("Need attention", counts.get("failed", 0))
    skipped.metric("Skipped", counts.get("skipped", 0))
    current = next((row.get("name", "") for row in report.get("files", []) if row.get("status") == "processing"), "")
    if current:
        st.markdown(f'<div class="bulk-current-file"><b>Processing</b><span>{escape(str(current))}</span></div>', unsafe_allow_html=True)
    if status == "completed":
        if counts.get("failed"):
            st.warning("The batch finished with files that need attention. Imported files are ready; check the report for the others.")
        else:
            st.success("Your batch is ready. Imported datasets and procedure files are available in their libraries.")
    elif status in {"cancelled", "interrupted"}:
        st.info("Processing stopped. Files already imported remain in your workspace. Unprocessed files are listed below.")
    elif status == "failed":
        st.error(str(report.get("error") or "This batch could not finish. Check its per-file report and retry the affected files."))
    else:
        st.caption("This job runs in the background while FRIB is open. You can keep using the app and return to this tab.")
        if st.button("Stop after current file", key="bulk_cancel", disabled=bool(report.get("cancel_requested")), width="stretch"):
            try:
                result = api_post(f"/ingestion/bulk/{job_id}/cancel")
                if isinstance(result, dict):
                    st.session_state["bulk_report"] = result
                st.rerun(scope="app")
            except Exception as exc:
                st.error("Could not stop the batch. " + friendly_error(exc))
    rows = [{"File": row.get("name", ""), "Type": row.get("kind", ""), "Status": row.get("status", ""),
             "Details": row.get("error") or row.get("message") or row.get("reason") or row.get("event_id") or row.get("document_id") or ""}
            for row in report.get("files", [])]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True, height=min(380, 80 + 35 * len(rows)))
    if status in TERMINAL:
        st.download_button("Download import report", json.dumps(report, indent=2, ensure_ascii=False),
                           file_name=f"{job_id}.json", mime="application/json", key="bulk_download_report", on_click="ignore")
        imported_events = [row for row in report.get("files", []) if row.get("status") == "imported" and row.get("event_id")]
        if imported_events:
            choice = st.selectbox("Dataset to explore", imported_events, format_func=lambda row: str(row.get("name") or row["event_id"]), key="bulk_open_dataset")
            st.button("Explore imported dataset", key="bulk_explore", type="primary", on_click=navigate_event,
                      args=(choice["event_id"],), width="stretch")
        st.caption("Procedure files were added without approval. Review them in Documents before using them for AI answers.")


def render_bulk_importer(api_get, api_post, api_upload_batch, friendly_error, navigate_event):
    section_header("Bring a whole collection.", "Upload a ZIP of your folder. Import it once and follow each file's progress.", "BULK IMPORT")
    try:
        raw_limits = api_get("/ingestion/bulk/limits")
        limits = {key: min(int(raw_limits.get(key, value)), value) for key, value in DEFAULT_LIMITS.items()}
        if any(value <= 0 for value in limits.values()):
            raise ValueError("Invalid import limits")
    except Exception as exc:
        st.error("Bulk import is unavailable. " + friendly_error(exc))
        st.caption("If you just updated FRIB, restart its launcher once to load the new import service.")
        return
    report = st.session_state.get("bulk_report", {})
    job_id = st.session_state.get("bulk_job_id")
    active = bool(job_id) and report.get("status") not in TERMINAL
    # A native multi-file/folder picker receives every file into Streamlit RAM
    # before Python can inspect their aggregate size. One size-capped archive
    # avoids an unbounded collection buffer; extraction happens on disk below.
    source = "ZIP"
    epoch = st.session_state.get("bulk_upload_epoch", 0)
    st.info("In Finder, right-click the folder you want to import and choose Compress. Upload the resulting ZIP here; subfolders and original files are preserved.")
    uploads = st.file_uploader("Choose a ZIP archive", type=["zip"], accept_multiple_files=False,
                              max_upload_size=max(1, limits["max_total_bytes"] // 1024 ** 2),
                              disabled=active, key=upload_widget_key(f"bulk_upload_{epoch}"))
    uploads = [uploads] if uploads and not isinstance(uploads, list) else uploads or []
    st.caption(f"Up to {limits['max_files']:,} files and {size_label(limits['max_total_bytes'])} expanded per batch; {size_label(limits['max_file_bytes'])} per data or procedure file. ZIP archives may be larger, but their contents follow the same limits.")
    st.caption("CSV, TSV and event JSON become datasets. LOG files preserve narrative evidence. PDF, Markdown and text files become unapproved documents. Existing event IDs and originals are preserved.")
    valid, selected_size = True, 0
    if uploads:
        try:
            selected_size = validate_selection(uploads, limits)
            st.markdown(f'<div class="bulk-selection"><b>{len(uploads):,} selected</b><span>{escape(size_label(selected_size))} to upload</span><span>Original files preserved</span></div>', unsafe_allow_html=True)
            with st.expander("Selected files", expanded=False):
                st.dataframe([{"File": item.name, "Size": size_label(upload_size(item))} for item in uploads], hide_index=True, width="stretch")
        except ValueError as exc:
            valid = False
            st.error(str(exc))
    with st.expander("Shared measurement mapping", expanded=False):
        st.caption("Leave this as {} for detected columns and file units. Supply the same validated mapping for a consistently formatted CSV collection. Files that need corrections are reported individually.")
        options_text = st.text_area("Import settings JSON", value="{}", key="bulk_options", height=110)
    try:
        options = parse_options(options_text)
    except (ValueError, TypeError) as exc:
        options, valid = {}, False
        st.error("Check the shared import settings: " + str(exc))
    signature = (source, epoch, tuple((str(item.name), upload_size(item), str(getattr(item, "file_id", ""))) for item in uploads), options_text)
    if st.session_state.get("bulk_selection_signature") != signature:
        st.session_state["bulk_confirm"] = False
        st.session_state["bulk_selection_signature"] = signature
    confirmed = st.checkbox("I have checked these files and want to import them", key="bulk_confirm", disabled=active)
    if st.button("Start bulk import", key="bulk_submit", type="primary", width="stretch", disabled=not uploads or not valid or not confirmed or active):
        transfer = st.progress(0.0, text="Sending files to the local import queue…")
        last_update = [0.0]
        def on_progress(sent, total):
            now = time.monotonic()
            if sent == total or now - last_update[0] >= .35:
                percentage = min(100, max(0, int(sent / total * 100))) if total else 0
                transfer.progress(percentage, text=f"{percentage}% · Uploading to the local import queue…")
                last_update[0] = now
        try:
            result = api_upload_batch(uploads, options, on_progress=on_progress)
            if not isinstance(result, dict) or not JOB_ID.fullmatch(str(result.get("job_id", ""))):
                raise ValueError("The import service did not return a valid job identifier.")
            st.session_state.update(bulk_job_id=result["job_id"], bulk_report=result, bulk_upload_epoch=epoch + 1)
            # The new uploader key releases large browser upload buffers after
            # the backend has staged them. Progress retains metadata only.
            st.rerun()
        except Exception as exc:
            transfer.empty()
            st.error("The batch was not queued. " + friendly_error(exc))
    if job_id:
        st.divider()
        st.markdown("### Import progress")
        runner = st.fragment(run_every="2s" if active else None)(_render_progress)
        runner(job_id, api_get, api_post, friendly_error, navigate_event)
