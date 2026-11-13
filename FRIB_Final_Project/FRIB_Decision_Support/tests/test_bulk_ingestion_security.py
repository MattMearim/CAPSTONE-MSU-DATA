"""Adversarial bulk ingestion runs against disposable, mock-only workspaces."""
from __future__ import annotations

import hashlib
from contextlib import nullcontext
import asyncio
import io
import json
import stat
import struct
import threading
import time
import zipfile

import pytest

from test_mixed_api import environment
from frib_ds.ingestion import bulk
from frib_ds.api import security
from frib_ds.storage.reset import DataLifecycleLock


CSV_FIRST = b"time [s],voltage [V]\r\n0,1\r\n1,2\r\n"
CSV_SECOND = b"time [s],voltage [V]\n0,3\n1,4\n"


def archive_bytes(entries, *, compression=zipfile.ZIP_DEFLATED):
    """Entries may specify Unix types without creating actual special files."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, contents, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            archive.writestr(info, contents)
    return output.getvalue()


def upload_bulk(client, files, *, options=None, **data):
    return client.post("/ingestion/bulk", files=[("files", (name, contents, "application/octet-stream")) for name, contents in files],
                       data={"options": json.dumps(options or {}), **data})


def test_streaming_dashboard_multipart_reaches_the_real_bulk_route(environment):
    from frib_ds.dashboard.bulk_client import MultipartBatch
    client, _, _ = environment
    capture, procedure = io.BytesIO(CSV_FIRST), io.BytesIO(b"# Training reference\nCheck the recorded measurements.\n")
    capture.name, procedure.name = "run-1/capture.csv", "references/procedure.md"
    body = MultipartBatch([capture, procedure])
    response = client.post("/ingestion/bulk", content=iter(body), headers={"Content-Type": body.content_type, "Content-Length": str(len(body))})
    job = finished_job(client, response)
    assert job["counts"]["imported"] == 2
    assert {row["name"] for row in job["files"]} == {capture.name, procedure.name}
    assert client.get("/documents").json()[0]["approved"] is False


def finished_job(client, response, timeout=10):
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        polled = client.get(f"/ingestion/bulk/{job['job_id']}")
        assert polled.status_code == 200, polled.text
        job = polled.json()
        if job["status"] in {"completed", "cancelled", "failed"} and job["processed_files"] == job["total_files"]:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Disposable bulk job did not finish: {job}")


def no_imports(client, state):
    assert client.get("/events").json() == []
    assert client.get("/documents").json() == []
    assert list(state["services"].files.event_dir.iterdir()) == []
    assert list(state["services"].documents.directory.iterdir()) == []
    assert not list((state["services"].config.data_dir / "bulk-jobs").rglob("*.upload"))


def test_entry_limit_counts_folders_across_multiple_archives(environment, monkeypatch):
    client, state, _ = environment
    monkeypatch.setenv("FRIB_BULK_MAX_FILES", "4")
    first = archive_bytes([("run-1/", b"", stat.S_IFDIR | 0o700),
                           ("run-1/capture.csv", CSV_FIRST, stat.S_IFREG | 0o600)])
    second = archive_bytes([("run-2/", b"", stat.S_IFDIR | 0o700),
                            ("run-2/metadata/", b"", stat.S_IFDIR | 0o700),
                            ("run-2/capture.csv", CSV_SECOND, stat.S_IFREG | 0o600)])
    response = upload_bulk(client, [("first.zip", first), ("second.zip", second)])
    assert response.status_code == 400, response.text
    assert "entries" in response.json()["detail"]
    no_imports(client, state)


@pytest.mark.parametrize("name", [
    "../outside.csv", "/outside.csv", "folder/../../outside.csv",
    "folder/../capture.csv", "folder\\capture.csv", "C:/outside.csv",
    "capture.csv:alternate", "folder//capture.csv", "folder/./capture.csv",
])
def test_zip_unsafe_member_is_rejected_before_any_file_is_imported(environment, name):
    client, state, temporary = environment
    outside = temporary / "outside.csv"
    outside.write_bytes(b"SYNTHETIC SENTINEL: never overwrite")
    contents = archive_bytes([
        ("safe/first.csv", CSV_FIRST, stat.S_IFREG | 0o600),
        (name, CSV_SECOND, stat.S_IFREG | 0o600),
    ])
    response = upload_bulk(client, [("unsafe.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)
    assert outside.read_bytes() == b"SYNTHETIC SENTINEL: never overwrite"


@pytest.mark.parametrize("mode", [stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFSOCK | 0o600, stat.S_IFCHR | 0o600])
def test_zip_symlinks_and_special_files_are_not_extracted(environment, mode):
    client, state, _ = environment
    payload = archive_bytes([
        ("capture.csv", CSV_FIRST, stat.S_IFREG | 0o600),
        ("link.csv", b"../../private.csv", mode),
    ])
    response = upload_bulk(client, [("special.zip", payload)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_encrypted_archive_member_is_refused_before_worker_start(environment):
    client, state, _ = environment
    payload = bytearray(archive_bytes([("capture.csv", CSV_FIRST, stat.S_IFREG | 0o600)]))
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    for offset in (local + 6, central + 8):
        flags = struct.unpack_from("<H", payload, offset)[0]
        struct.pack_into("<H", payload, offset, flags | 1)
    response = upload_bulk(client, [("encrypted.zip", bytes(payload))])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_same_leaf_names_from_different_folders_preserve_distinct_originals(environment):
    client, state, _ = environment
    payload = archive_bytes([
        ("first/capture.csv", CSV_FIRST, stat.S_IFREG | 0o600),
        ("second/capture.csv", CSV_SECOND, stat.S_IFREG | 0o600),
    ])
    job = finished_job(client, upload_bulk(client, [("folder.zip", payload)]))
    assert job["counts"]["imported"] == 2 and job["counts"]["failed"] == 0
    event_ids = [entry["event_id"] for entry in job["files"] if entry["status"] == "imported"]
    assert len(event_ids) == len(set(event_ids)) == 2
    original_checksums = set()
    for event_id in event_ids:
        files = client.get(f"/events/{event_id}/files").json()
        assert len(files) == 1
        original = client.get(f"/events/{event_id}/files/{files[0]['file_id']}/download").content
        original_checksums.add(hashlib.sha256(original).hexdigest())
        assert files[0]["checksum"] == hashlib.sha256(original).hexdigest()
    assert original_checksums == {hashlib.sha256(CSV_FIRST).hexdigest(), hashlib.sha256(CSV_SECOND).hexdigest()}
    assert len(state["services"].repo.list_events()) == 2


def test_bulk_documents_require_explicit_approval_before_entering_retrieval(environment):
    client, state, _ = environment
    original = b"# FICTIONAL TRAINING ONLY\n\nReview cavity trip evidence with a qualified person.\n"
    job = finished_job(client, upload_bulk(client, [("procedures/reference.md", original)]))
    assert job["counts"]["imported"] == 1, job
    document_id = job["files"][0]["document_id"]
    row = state["services"].repo.get_document(document_id)
    assert row["approved"] is False and row["indexed_chunks"] == 0
    assert client.get(f"/documents/{document_id}/download").content == original
    assert state["services"].repo.approved_document_chunks() == []


def test_bad_file_cannot_partially_import_or_prevent_other_files_from_finishing(environment):
    client, state, _ = environment
    job = finished_job(client, upload_bulk(client, [
        ("good.csv", CSV_FIRST),
        ("broken.csv", b'time [s],voltage [V]\n0,"unterminated\n'),
        ("good-again.csv", CSV_SECOND),
    ]))
    assert job["counts"]["imported"] == 2 and job["counts"]["failed"] == 1, job
    failed = [entry for entry in job["files"] if entry["status"] == "failed"]
    assert len(failed) == 1 and failed[0].get("error")
    assert not failed[0].get("event_id") and not failed[0].get("document_id")
    saved = state["services"].repo.list_events()
    assert len(saved) == 2
    assert len(list(state["services"].files.event_dir.iterdir())) == 2
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unknown_or_unrelated_job_ids_never_reveal_paths_or_create_jobs(environment, method):
    client, state, _ = environment
    url = "/ingestion/bulk/BULK-" + "f" * 32 + ("/cancel" if method == "POST" else "")
    response = client.request(method, url)
    assert response.status_code == 404, response.text
    assert str(state["services"].config.data_dir) not in response.text
    no_imports(client, state)


@pytest.mark.parametrize("setting,value,entries", [
    ("FRIB_BULK_MAX_FILES", "1", [("capture.csv", CSV_FIRST), (".DS_Store", b"metadata")]),
    ("FRIB_BULK_MAX_FILE_BYTES", "16", [("capture.csv", CSV_FIRST)]),
    ("FRIB_BULK_MAX_TOTAL_BYTES", "50", [("first.csv", CSV_FIRST), ("second.csv", CSV_SECOND)]),
])
def test_archive_limits_apply_before_import_and_include_ignored_members(environment, monkeypatch, setting, value, entries):
    client, state, _ = environment
    monkeypatch.setenv(setting, value)
    contents = archive_bytes([(name, payload, stat.S_IFREG | 0o600) for name, payload in entries])
    response = upload_bulk(client, [("limited.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_high_compression_ratio_is_rejected_without_expanding_the_member(environment, monkeypatch):
    client, state, _ = environment
    monkeypatch.setattr(bulk, "MAX_COMPRESSION_RATIO", 2)
    contents = archive_bytes([("capture.csv", b"a" * 4096, stat.S_IFREG | 0o600)])
    response = upload_bulk(client, [("compressed.zip", contents)])
    assert response.status_code == 400, response.text
    assert "compression" in response.text.lower()
    no_imports(client, state)


@pytest.mark.parametrize("names", [
    ["same.csv", "same.csv"],
    ["folder/capture.csv", "FOLDER/CAPTURE.csv"],
])
def test_duplicate_archive_paths_cannot_silently_replace_prior_input(environment, names):
    client, state, _ = environment
    with pytest.warns(UserWarning) if names[0] == names[1] else nullcontext():
        contents = archive_bytes([(names[0], CSV_FIRST, stat.S_IFREG | 0o600), (names[1], CSV_SECOND, stat.S_IFREG | 0o600)])
    response = upload_bulk(client, [("duplicates.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_archive_crc_failure_aborts_all_staged_members_and_imports(environment):
    client, state, _ = environment
    contents = bytearray(archive_bytes([
        ("first.csv", CSV_FIRST, stat.S_IFREG | 0o600),
        ("second.csv", CSV_SECOND, stat.S_IFREG | 0o600),
    ], compression=zipfile.ZIP_STORED))
    position = contents.index(CSV_SECOND)
    contents[position + len(CSV_SECOND) - 1] ^= 0x01
    response = upload_bulk(client, [("damaged.zip", bytes(contents))])
    assert response.status_code == 400, response.text
    no_imports(client, state)
    root = state["services"].config.data_dir / "bulk-jobs"
    assert not list(root.rglob("*.upload"))


def test_nested_archive_is_rejected_without_creating_nested_jobs(environment):
    client, state, _ = environment
    inner = archive_bytes([("capture.csv", CSV_FIRST, stat.S_IFREG | 0o600)])
    contents = archive_bytes([("folder/nested.ZIP", inner, stat.S_IFREG | 0o600)])
    response = upload_bulk(client, [("outer.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_embedded_nul_archive_name_cannot_be_silently_truncated(environment):
    client, state, _ = environment
    original_name = b"capture.csv!hidden"
    contents = archive_bytes([(original_name.decode(), CSV_FIRST, stat.S_IFREG | 0o600)])
    contents = contents.replace(original_name, original_name.replace(b"!", b"\0"))
    response = upload_bulk(client, [("nul.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def staged_manager(tmp_path, names=("first.csv", "second.csv")):
    manager = bulk.BulkImportManager(tmp_path / "data")
    job = manager.begin()
    for name in names:
        path = manager.staged_path(job["job_id"])
        path.write_bytes(CSV_FIRST)
        manager.add_file(job["job_id"], name, path)
    return manager, job


def wait_manager(manager, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        report = manager.status(job_id)
        if (report["status"] in {"completed", "cancelled", "failed"}
                and not (manager.root / job_id / "staged").exists()):
            return report
        time.sleep(0.01)
    raise AssertionError("Disposable bulk worker did not finish")


def test_cancel_finishes_current_file_preserves_prior_import_and_never_processes_remaining_files(tmp_path):
    manager, job = staged_manager(tmp_path)
    started, release = threading.Event(), threading.Event()
    calls = []

    def process(path, name, kind, options, approved):
        calls.append(name)
        started.set()
        assert release.wait(5), "Test must release the disposable worker"
        return {"event_id": "SYNTHETIC-FIRST"}

    manager.submit(job["job_id"], process, {}, False, "original", lambda: "original")
    try:
        assert started.wait(5)
        cancelled = manager.cancel(job["job_id"])
        assert cancelled["cancel_requested"] is True
        assert calls == ["first.csv"]
    finally:
        release.set()
    report = wait_manager(manager, job["job_id"])
    assert report["status"] == "cancelled"
    assert report["counts"] == {"imported": 1, "failed": 0, "skipped": 0, "cancelled": 1}
    assert report["files"][0]["event_id"] == "SYNTHETIC-FIRST"
    assert calls == ["first.csv"]
    assert not list(manager.root.rglob("*.upload"))


def test_reset_generation_change_cancels_remaining_files_before_their_processor_runs(tmp_path):
    manager, job = staged_manager(tmp_path)
    generation = ["before-reset"]
    calls = []

    def process(path, name, kind, options, approved):
        calls.append(name)
        generation[0] = "after-reset"
        return {"event_id": "SYNTHETIC-FIRST"}

    manager.submit(job["job_id"], process, {}, False, "before-reset", lambda: generation[0])
    report = wait_manager(manager, job["job_id"])
    assert calls == ["first.csv"]
    assert report["status"] == "cancelled" and report["counts"]["cancelled"] == 1
    assert "reset" in report["message"].lower()
    assert not list(manager.root.rglob("*.upload"))


def test_worker_error_report_does_not_expose_private_filesystem_or_secret_exception(tmp_path):
    manager, job = staged_manager(tmp_path, names=("broken.csv",))

    def process(*args):
        raise RuntimeError("PRIVATE-TOKEN in /private/synthetic/secret.txt")

    manager.submit(job["job_id"], process, {}, False, None, lambda: None)
    report = wait_manager(manager, job["job_id"])
    serialized = json.dumps(report)
    assert report["counts"]["failed"] == 1
    assert "PRIVATE-TOKEN" not in serialized and "/private/synthetic" not in serialized
    assert "_path" not in serialized
    assert not list(manager.root.rglob("*.upload"))


def test_cancellation_while_waiting_for_lifecycle_lock_never_runs_a_processor(tmp_path):
    manager, job = staged_manager(tmp_path)
    lock = DataLifecycleLock(manager.data_dir)
    calls = []
    assert lock.try_acquire()
    try:
        manager.submit(job["job_id"], lambda *args: calls.append(True) or {}, {}, False, None, lambda: None)
        manager.cancel(job["job_id"])
        report = wait_manager(manager, job["job_id"])
    finally:
        lock.close()
    assert calls == []
    assert report["counts"] == {"imported": 0, "failed": 0, "skipped": 0, "cancelled": 2}
    assert not list(manager.root.rglob("*.upload"))


def test_active_job_limit_rejects_extra_work_and_abort_releases_capacity(tmp_path):
    manager = bulk.BulkImportManager(tmp_path / "data")
    jobs = [manager.begin() for _ in range(bulk.MAX_JOBS)]
    try:
        with pytest.raises(bulk.BulkBusyError):
            manager.begin()
        manager.abort(jobs.pop()["job_id"])
        jobs.append(manager.begin())
    finally:
        for job in jobs:
            manager.abort(job["job_id"])
    assert list(manager.root.iterdir()) == []


@pytest.mark.parametrize("options", [{"event_id": "SHARED-ID"}, {"dataset_name": "shared"}, {"approved_documents": True}])
def test_shared_identity_or_approval_options_cannot_override_per_file_controls(environment, options):
    client, state, _ = environment
    response = upload_bulk(client, [("capture.csv", CSV_FIRST)], options=options)
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_attachment_failure_rolls_back_just_its_event_and_keeps_other_originals(environment, monkeypatch):
    client, state, _ = environment
    store = state["services"].files
    original_save = store.save_attachment

    def failing_attachment(event_id, name, contents):
        if name == "cannot-store.csv":
            raise OSError("SYNTHETIC storage failure")
        return original_save(event_id, name, contents)

    monkeypatch.setattr(store, "save_attachment", failing_attachment)
    job = finished_job(client, upload_bulk(client, [("cannot-store.csv", CSV_FIRST), ("good.csv", CSV_SECOND)]))
    assert job["counts"]["failed"] == 1 and job["counts"]["imported"] == 1
    assert len(state["services"].repo.list_events()) == 1
    assert len(list(store.event_dir.iterdir())) == 1
    successful = next(entry for entry in job["files"] if entry["status"] == "imported")
    attachments = client.get(f"/events/{successful['event_id']}/files").json()
    assert len(attachments) == 1
    downloaded = client.get(f"/events/{successful['event_id']}/files/{attachments[0]['file_id']}/download")
    assert downloaded.content == CSV_SECOND


def test_duplicate_json_event_ids_cannot_overwrite_the_first_original(environment):
    client, state, _ = environment
    payload = json.dumps({"event_id": "SYNTHETIC-SAME-ID", "domain": "other", "event_type": "evidence_record",
                          "provenance": {"source": "disposable_security_test"}}).encode()
    job = finished_job(client, upload_bulk(client, [("first/event.json", payload), ("second/event.json", payload)]))
    assert job["counts"]["imported"] == 1 and job["counts"]["failed"] == 1, job
    assert len(state["services"].repo.list_events()) == 1
    event = client.get("/events/SYNTHETIC-SAME-ID").json()
    assert event["metadata"]["bulk_source_path"] == "first/event.json"
    attachments = client.get("/events/SYNTHETIC-SAME-ID/files").json()
    assert len(attachments) == 1
    assert client.get(f"/events/SYNTHETIC-SAME-ID/files/{attachments[0]['file_id']}/download").content == payload


@pytest.mark.parametrize("path,method,allowed", [
    ("/ingestion/bulk", "POST", True),
    ("/ingestion/import", "POST", False),
    ("/events", "POST", False),
    ("/ingestion/bulk", "GET", False),
    ("/ingestion/bulk/BULK-synthetic/cancel", "POST", False),
])
def test_larger_bulk_body_budget_is_scoped_to_submission_and_cannot_weaken_other_routes(monkeypatch, path, method, allowed):
    monkeypatch.setattr(security, "MAX_REQUEST_BYTES", 64)
    messages = iter([{"type": "http.request", "body": b"x" * 65, "more_body": False}])
    output, reached = [], []

    async def receive():
        return next(messages)

    async def send(message):
        output.append(message)

    async def route(scope, receive, send):
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = security.LocalRequestSecurityMiddleware(route)
    scope = {"type": "http", "method": method, "path": path, "headers": [(b"host", b"127.0.0.1")]}
    asyncio.run(middleware(scope, receive, send))
    assert output[0]["status"] == (200 if allowed else 413)
    assert bool(reached) is allowed


@pytest.mark.parametrize("compression", [zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2])
def test_archive_compression_with_unbounded_decoder_allocations_is_refused(environment, compression):
    client, state, _ = environment
    contents = archive_bytes([("capture.csv", CSV_FIRST, stat.S_IFREG | 0o600)], compression=compression)
    response = upload_bulk(client, [("unapproved-method.zip", contents)])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_forged_archive_declared_size_cannot_bypass_actual_byte_accounting(environment):
    client, state, _ = environment
    contents = bytearray(archive_bytes([("capture.csv", CSV_FIRST, stat.S_IFREG | 0o600)], compression=zipfile.ZIP_STORED))
    central = contents.index(b"PK\x01\x02")
    declared = struct.unpack_from("<I", contents, central + 24)[0]
    struct.pack_into("<I", contents, central + 24, declared + 1)
    response = upload_bulk(client, [("forged-size.zip", bytes(contents))])
    assert response.status_code == 400, response.text
    no_imports(client, state)


def test_reset_removes_completed_bulk_report_names_and_staged_uploads(environment):
    client, state, _ = environment
    name = "SYNTHETIC-CONFIDENTIAL-NAME.csv"
    job = finished_job(client, upload_bulk(client, [(name, CSV_FIRST)]))
    assert name in json.dumps(job)
    response = client.post("/system/reset", json={"confirmation": "RESET"})
    assert response.status_code == 200, response.text
    assert client.get("/events").json() == []
    manager = bulk.get_bulk_manager(str(state["services"].config.data_dir))
    assert not list(manager.root.rglob("*.upload"))
    for path in manager.root.rglob("*.json"):
        assert name.encode() not in path.read_bytes()
    status = client.get(f"/ingestion/bulk/{job['job_id']}")
    assert status.status_code in {200, 404}
    if status.status_code == 200:
        assert status.json()["files"] == [] and name not in status.text


def test_reset_cancels_lock_waiting_worker_and_removes_original_staging_before_return(tmp_path):
    manager, job = staged_manager(tmp_path, names=("SYNTHETIC-PRIVATE-FIRST.csv", "SYNTHETIC-PRIVATE-SECOND.csv"))
    lock = DataLifecycleLock(manager.data_dir)
    calls = []
    assert lock.try_acquire()
    try:
        manager.submit(job["job_id"], lambda *args: calls.append(True) or {}, {}, False, "old", lambda: "old")
        manager.reset()
        assert not list(manager.root.rglob("*.upload"))
        report = manager.status(job["job_id"])
        assert report["files"] == [] and "SYNTHETIC-PRIVATE" not in json.dumps(report)
    finally:
        lock.close()
    report = wait_manager(manager, job["job_id"])
    assert calls == [] and report["files"] == []


def test_staged_file_symlink_replacement_cannot_read_outside_original_or_run_processor(tmp_path):
    manager, job = staged_manager(tmp_path, names=("capture.csv",))
    private = tmp_path / "private.csv"
    private.write_bytes(b"SYNTHETIC PRIVATE CONTENT")
    entry = job["files"][0]
    staged = manager.root / job["job_id"] / "staged" / entry["_path"]
    staged.unlink()
    staged.symlink_to(private)
    calls = []
    manager.submit(job["job_id"], lambda *args: calls.append(True) or {}, {}, False, None, lambda: None)
    report = wait_manager(manager, job["job_id"])
    assert calls == [] and report["counts"]["failed"] == 1
    assert private.read_bytes() == b"SYNTHETIC PRIVATE CONTENT"
    assert "SYNTHETIC PRIVATE CONTENT" not in json.dumps(report)


def test_cancel_from_another_manager_sharing_workspace_stops_remaining_files(tmp_path):
    manager, job = staged_manager(tmp_path)
    started, release = threading.Event(), threading.Event()
    calls = []

    def process(path, name, *args):
        calls.append(name)
        if name == "first.csv":
            started.set()
            assert release.wait(5), "Test must release the disposable worker"
        return {"event_id": "SYNTHETIC-FIRST"}

    manager.submit(job["job_id"], process, {}, False, None, lambda: None)
    other = bulk.BulkImportManager(manager.data_dir)
    try:
        assert started.wait(5)
        response = other.cancel(job["job_id"])
        assert response["cancel_requested"] is True
    finally:
        release.set()
    report = wait_manager(manager, job["job_id"])
    assert calls == ["first.csv"]
    assert report["status"] == "cancelled"
    assert report["counts"] == {"imported": 1, "failed": 0, "skipped": 0, "cancelled": 1}
    assert other.status(job["job_id"])["status"] == "cancelled"
