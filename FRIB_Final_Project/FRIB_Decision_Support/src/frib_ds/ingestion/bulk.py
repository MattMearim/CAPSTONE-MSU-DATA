"""Disk-staged, bounded bulk imports with one worker and truthful progress.

Archive paths are display metadata only. Imports call the existing validated
single-file workflows, with the data lifecycle lock held for one file at a
time. Cancelling never rolls back files that already finished importing.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from pathlib import Path, PurePosixPath
from queue import Empty, Queue
import re
import shutil
import stat
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Callable
import uuid
import zipfile

from frib_ds.storage.reset import DataLifecycleLock

MAX_FILES = 1000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000
MAX_JOBS = 2
MAX_RETAINED_REPORTS = 20
CHUNK_BYTES = 1024 * 1024
DATASET_SUFFIXES = {".csv", ".tsv", ".json", ".log"}
DOCUMENT_SUFFIXES = {".pdf", ".txt", ".md"}
SUPPORTED_SUFFIXES = DATASET_SUFFIXES | DOCUMENT_SUFFIXES
JOB_PATTERN = re.compile(r"^BULK-[a-f0-9]{32}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class BulkImportError(ValueError):
    pass


class BulkBusyError(BulkImportError):
    pass


def _configured_limit(name: str, maximum: int) -> int:
    try:
        value = int(os.getenv(name, maximum))
    except (ValueError, TypeError):
        value = maximum
    return max(1, min(value, maximum))


def bulk_limits() -> dict:
    """Environment settings can lower the server's hard safety ceilings."""
    return {"max_files": _configured_limit("FRIB_BULK_MAX_FILES", MAX_FILES),
            "max_total_bytes": _configured_limit("FRIB_BULK_MAX_TOTAL_BYTES", MAX_TOTAL_BYTES),
            "max_file_bytes": _configured_limit("FRIB_BULK_MAX_FILE_BYTES", MAX_FILE_BYTES)}


def safe_relative_name(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 1000
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or "\\" in value or ":" in value or value.startswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise BulkImportError("File names must be safe relative folder paths without '..', backslashes or drive names.")
    parts = PurePosixPath(value).parts
    if len(parts) > 32:
        raise BulkImportError("Folder nesting exceeds the limit of 32 levels.")
    for part in parts:
        if len(part) > 240 or part.endswith((".", " ")) or part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise BulkImportError("A file or folder name is too long or is reserved by the operating system.")
    return "/".join(parts)


def ignored_name(name: str) -> bool:
    return any(part.startswith(".") or part == "__MACOSX" for part in PurePosixPath(name).parts)


def file_kind(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    return "dataset" if suffix in DATASET_SUFFIXES else "document" if suffix in DOCUMENT_SUFFIXES else "unsupported"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    if path.is_symlink():
        raise BulkImportError("Bulk import status cannot be a symbolic link.")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class BulkImportManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.root = self.data_dir / "bulk-jobs"
        if self.root.is_symlink():
            raise BulkImportError("The bulk import staging directory cannot be a symbolic link.")
        self.root.mkdir(parents=True, exist_ok=True)
        self._mutex = Lock()
        self._slots = BoundedSemaphore(MAX_JOBS)
        self._queue: Queue = Queue()
        self._worker: Thread | None = None
        self._jobs: dict[str, dict] = {}
        self._cancellations: dict[str, Event] = {}
        self._pending: set[str] = set()

    def begin(self) -> dict:
        if not self._slots.acquire(blocking=False):
            raise BulkBusyError("Two bulk imports are already active. Wait for one to finish or cancel it before adding more.")
        job_id = f"BULK-{uuid.uuid4().hex}"
        directory = self.root / job_id
        try:
            self._prune_reports()
            directory.mkdir(mode=0o700, exist_ok=False)
            (directory / "staged").mkdir(mode=0o700)
            job = {"job_id": job_id, "status": "uploading", "created_at": _now(), "updated_at": _now(),
                   "total_files": 0, "processed_files": 0, "uploaded_bytes": 0, "expanded_bytes": 0,
                   "counts": {"imported": 0, "failed": 0, "skipped": 0, "cancelled": 0}, "files": [],
                   "limits": bulk_limits(), "cancel_requested": False,
                   "message": "Receiving and checking files; importing starts after archive safety checks finish."}
            with self._mutex:
                self._jobs[job_id] = job
                self._cancellations[job_id] = Event()
                self._pending.add(job_id)
            return job
        except BaseException:
            self._slots.release()
            raise

    def _prune_reports(self) -> None:
        with self._mutex:
            finished = [job for job in self._jobs.values() if job["job_id"] not in self._pending and job["status"] in {"completed", "cancelled", "failed"}]
            finished.sort(key=lambda job: job["updated_at"], reverse=True)
            for job in finished[MAX_RETAINED_REPORTS:]:
                self._jobs.pop(job["job_id"], None)
                self._cancellations.pop(job["job_id"], None)
        directories = sorted((path for path in self.root.iterdir() if JOB_PATTERN.fullmatch(path.name) and path.is_dir() and not path.is_symlink()), key=lambda path: path.stat().st_mtime, reverse=True)
        for directory in directories[MAX_RETAINED_REPORTS + MAX_JOBS:]:
            with self._mutex:
                active = directory.name in self._pending
            if not active:
                shutil.rmtree(directory)

    def _directory(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not JOB_PATTERN.fullmatch(job_id):
            raise KeyError("Bulk import not found")
        path = self.root / job_id
        if path.is_symlink() or path.parent.resolve() != self.root.resolve():
            raise BulkImportError("Unsafe bulk import staging location.")
        return path

    def staged_path(self, job_id: str) -> Path:
        directory = self._directory(job_id) / "staged"
        if directory.is_symlink() or not directory.is_dir():
            raise BulkImportError("Unsafe bulk import staging directory.")
        return directory / f"{uuid.uuid4().hex}.upload"

    def abort(self, job_id: str) -> None:
        with self._mutex:
            removed = self._jobs.pop(job_id, None)
            self._cancellations.pop(job_id, None)
            self._pending.discard(job_id)
        if removed:
            directory = self._directory(job_id)
            if directory.is_dir():
                shutil.rmtree(directory)
            self._slots.release()

    def _entry(self, job: dict, name: str, size: int, path: Path | None, status: str = "queued", reason: str | None = None) -> None:
        if len(job["files"]) >= job["limits"]["max_files"]:
            raise BulkImportError(f"A batch may contain at most {job['limits']['max_files']} files, including ignored or unsupported files.")
        if any(item["name"].casefold() == name.casefold() for item in job["files"]):
            raise BulkImportError("The batch contains duplicate file paths, including names differing only by letter case.")
        entry = {"name": name, "size_bytes": size, "kind": file_kind(name), "status": status}
        if path is not None:
            entry["_path"] = path.name
        if reason:
            entry["message"] = reason
        job["files"].append(entry)

    def add_file(self, job_id: str, name: str, path: Path, size_bytes: int | None = None) -> None:
        job = self._jobs[job_id]
        if self.is_cancelled(job_id):
            raise BulkImportError("The bulk upload was cancelled or project data was reset. Start a new batch when ready.")
        name = safe_relative_name(name)
        size = path.stat().st_size if size_bytes is None else size_bytes
        if path.is_symlink() or path.parent != self._directory(job_id) / "staged":
            raise BulkImportError("Unsafe staged upload.")
        if PurePosixPath(name).suffix.lower() == ".zip":
            self._add_zip(job, name, path)
            path.unlink(missing_ok=True)
            return
        job["_entry_count"] = job.get("_entry_count", 0) + 1
        if job["_entry_count"] > job["limits"]["max_files"]:
            raise BulkImportError("Combined inputs exceed the batch entry limit, including folders and hidden metadata.")
        job["expanded_bytes"] += size
        if job["expanded_bytes"] > job["limits"]["max_total_bytes"]:
            raise BulkImportError("Combined file contents exceed the batch size limit.")
        if size > job["limits"]["max_file_bytes"]:
            self._entry(job, name, size, None, "failed")
            job["files"][-1]["error"] = "This file exceeds the 20 MB individual import limit. Split it into smaller captures; its contents were not truncated or imported."
            path.unlink(missing_ok=True)
            return
        skip = ignored_name(name) or file_kind(name) == "unsupported"
        self._entry(job, name, size, None if skip else path, "skipped" if skip else "queued",
                    "Hidden/system metadata file ignored." if ignored_name(name) else "Unsupported file type; use CSV, TSV, JSON, PDF, TXT or MD." if skip else None)
        if skip:
            path.unlink(missing_ok=True)

    def _add_zip(self, job: dict, archive_name: str, archive_path: Path) -> None:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                entry_count = job.get("_entry_count", 0) + len(infos)
                if entry_count > job["limits"]["max_files"]:
                    raise BulkImportError("ZIP contains too many combined batch entries, including folders and hidden metadata.")
                checked = []
                names = {entry["name"].casefold() for entry in job["files"]}
                expanded = job["expanded_bytes"]
                for info in infos:
                    # ZipInfo.filename is silently truncated at a NUL byte.
                    if "\x00" in info.orig_filename:
                        raise BulkImportError("ZIP member names cannot contain NUL bytes.")
                    raw_name = info.filename[:-1] if info.is_dir() else info.filename
                    name = safe_relative_name(raw_name)
                    mode = info.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or (kind == stat.S_IFDIR and not info.is_dir()):
                        raise BulkImportError("ZIP symbolic links and special filesystem objects are not supported.")
                    if info.flag_bits & 1:
                        raise BulkImportError("Encrypted ZIP files are not supported.")
                    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                        raise BulkImportError("Use a standard ZIP with stored or deflated compression; this ZIP compression method is not supported.")
                    if info.is_dir():
                        continue
                    # A ZIP is a container, not another destination folder;
                    # preserve only its own original relative member paths.
                    if name.casefold() in names:
                        raise BulkImportError("ZIP contains duplicate file paths, including names differing only by letter case.")
                    names.add(name.casefold())
                    if PurePosixPath(name).suffix.lower() == ".zip":
                        raise BulkImportError("Nested ZIP archives are not supported. Unzip them before adding the folder.")
                    if info.file_size > job["limits"]["max_file_bytes"]:
                        raise BulkImportError("A ZIP member exceeds the 20 MB individual file limit.")
                    if info.file_size and (not info.compress_size or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                        raise BulkImportError("ZIP compression ratio exceeds the safe limit.")
                    expanded += info.file_size
                    if expanded > job["limits"]["max_total_bytes"]:
                        raise BulkImportError("Expanded ZIP contents exceed the batch size limit.")
                    checked.append((info, name))
                if len(job["files"]) + len(checked) > job["limits"]["max_files"]:
                    raise BulkImportError("Combined inputs exceed the batch file count limit.")
                if shutil.disk_usage(self.root).free < (expanded - job["expanded_bytes"]) + 64 * 1024 * 1024:
                    raise BulkImportError("There is not enough free disk space to stage this expanded ZIP safely. Free local storage or import a smaller batch.")
                job["_entry_count"] = entry_count
                # Preflight every member before reading any archive contents.
                actual_expanded = job["expanded_bytes"]
                for info, name in checked:
                    if ignored_name(name) or file_kind(name) == "unsupported":
                        self._entry(job, name, info.file_size, None, "skipped", "Hidden/system metadata file ignored." if ignored_name(name) else "Unsupported file type.")
                        actual_expanded += info.file_size
                        continue
                    output = self.staged_path(job["job_id"])
                    total = 0
                    with archive.open(info) as source, output.open("xb") as target:
                        while chunk := source.read(CHUNK_BYTES):
                            total += len(chunk)
                            actual_expanded += len(chunk)
                            if total > job["limits"]["max_file_bytes"] or actual_expanded > job["limits"]["max_total_bytes"]:
                                raise BulkImportError("Actual expanded ZIP contents exceed the safe size limit.")
                            target.write(chunk)
                    if total != info.file_size:
                        raise BulkImportError("ZIP member size does not match its declared size.")
                    self._entry(job, name, total, output)
                job["expanded_bytes"] = actual_expanded
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
            raise BulkImportError("The ZIP is damaged or uses unsupported compression. Create a standard ZIP and try again.") from exc

    def submit(self, job_id: str, processor: Callable, options: dict, approved_documents: bool, generation: str | None, generation_reader: Callable) -> dict:
        job = self._jobs[job_id]
        if self.is_cancelled(job_id):
            raise BulkImportError("The bulk upload was cancelled or project data was reset. Start a new batch when ready.")
        if not job["files"]:
            raise BulkImportError("No files were found. Choose CSV, TSV, JSON, PDF, TXT, MD or a ZIP containing them.")
        job.update(status="queued", total_files=len(job["files"]), reset_generation=generation,
                   message="Queued. Original files will be validated one at a time.")
        with self._mutex:
            self._persist(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = Thread(target=self._run, daemon=True, name="frib-bulk-import")
                self._worker.start()
            self._queue.put((job_id, processor, options, approved_documents, generation_reader))
        return self.status(job_id)

    def _persist(self, job: dict) -> None:
        job["updated_at"] = _now()
        _write_json(self._directory(job["job_id"]) / "status.json", {**self._public(job), "_owner_pid": os.getpid()})

    def _public(self, job: dict) -> dict:
        result = {key: value for key, value in job.items() if key != "reset_generation" and not key.startswith("_")}
        result["files"] = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in job["files"]]
        counts = Counter(entry["status"] for entry in result["files"])
        result["counts"] = {key: counts.get(key, 0) for key in ("imported", "failed", "skipped", "cancelled")}
        result["processed_files"] = sum(result["counts"].values())
        if job["job_id"] in self._pending and job["status"] in {"completed", "cancelled", "failed"}:
            result.update(status="running", message="Finishing local staging cleanup. Imported files are already saved.")
        return result

    def status(self, job_id: str) -> dict:
        directory = self._directory(job_id)
        with self._mutex:
            if job_id in self._jobs:
                return self._public(self._jobs[job_id])
        status_path = directory / "status.json"
        if status_path.is_symlink() or not status_path.is_file() or status_path.stat().st_size > 16 * 1024 * 1024:
            raise KeyError("Bulk import not found")
        result = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("files"), list):
            raise BulkImportError("Bulk import report is malformed.")
        owner_pid = result.pop("_owner_pid", None)
        if result.get("status") in {"queued", "running", "uploading"}:
            owner_alive = isinstance(owner_pid, int) and owner_pid > 0
            if owner_alive and os.name != "nt":
                try:
                    os.kill(owner_pid, 0)
                except ProcessLookupError:
                    owner_alive = False
                except PermissionError:
                    pass
            worker_lock = DataLifecycleLock(self.root)
            try:
                locked = worker_lock.try_acquire()
                if not owner_alive and locked:
                    result.update(status="interrupted", message="The application restarted before this import finished. Completed files remain saved; add the remaining files as a new batch.")
                    for entry in result["files"]:
                        if entry.get("status") in {"queued", "processing"}:
                            entry.update(status="cancelled", message="The previous application session was interrupted.")
                    counts = Counter(entry.get("status") for entry in result["files"])
                    result["counts"] = {key: counts.get(key, 0) for key in ("imported", "failed", "skipped", "cancelled")}
                    result["processed_files"] = sum(result["counts"].values())
                    staged = directory / "staged"
                    if staged.is_symlink():
                        raise BulkImportError("Unsafe interrupted import staging directory.")
                    if staged.exists():
                        shutil.rmtree(staged)
                    _write_json(status_path, result)
            finally:
                worker_lock.close()
            if (directory / "cancel.request").is_file() and result.get("status") in {"queued", "running", "uploading"}:
                result.update(cancel_requested=True, message="Cancellation requested. The current file will finish safely; remaining files will be skipped.")
        return result

    def is_cancelled(self, job_id: str) -> bool:
        return self._cancellations[job_id].is_set() or (self._directory(job_id) / "cancel.request").is_file()

    def reset(self) -> None:
        """Called under the data lifecycle lock: purge uploaded staging/reports.

        A worker already waiting on the lock sees its cancellation before it can
        commit another file. Minimal in-flight control state contains no names
        or evidence and is reclaimed when that worker exits.
        """
        retained = set()
        with self._mutex:
            for job_id, job in list(self._jobs.items()):
                active = job_id in self._pending
                if active:
                    self._cancellations[job_id].set()
                    job.update(status="cancelled", cancel_requested=True, files=[], total_files=0,
                               message="Project data was reset. Uploaded staging files and import report details were removed.")
                    retained.add(job_id)
                    self._persist(job)
                else:
                    self._jobs.pop(job_id, None)
                    self._cancellations.pop(job_id, None)
        for directory in self.root.iterdir():
            if not JOB_PATTERN.fullmatch(directory.name):
                continue
            if directory.is_symlink():
                raise BulkImportError("Reset refused: a bulk import staging directory is a symbolic link.")
            if not directory.is_dir():
                raise BulkImportError("Reset refused: a bulk import staging directory is not a regular directory.")
            if directory.name in retained:
                staged = directory / "staged"
                if staged.is_symlink():
                    raise BulkImportError("Reset refused: bulk staging is a symbolic link.")
                if staged.exists():
                    shutil.rmtree(staged)
            else:
                shutil.rmtree(directory)

    def cancel(self, job_id: str) -> dict:
        self._directory(job_id)
        with self._mutex:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                if job["status"] in {"uploading", "queued", "running"}:
                    job["cancel_requested"] = True
                    job["message"] = "Cancellation requested. The current file will finish safely; remaining files will be skipped."
                    self._cancellations[job_id].set()
                    self._persist(job)
                return self._public(job)
        # A different local API process may own this job's worker. Persist a
        # bounded marker so its between-file checks receive the cancellation.
        result = self.status(job_id)
        if result.get("status") in {"queued", "running", "uploading"}:
            marker = self._directory(job_id) / "cancel.request"
            if marker.is_symlink():
                raise BulkImportError("Unsafe cancellation control file.")
            marker.touch(exist_ok=True)
            result.update(cancel_requested=True, message="Cancellation requested. The current file will finish safely; remaining files will be skipped.")
            return result
        return self.status(job_id)

    def _run(self) -> None:
        while True:
            try:
                job_id, processor, options, approved_documents, generation_reader = self._queue.get(timeout=0.5)
            except Empty:
                with self._mutex:
                    if self._queue.empty():
                        self._worker = None
                        return
                continue
            job = self._jobs[job_id]
            cancel = self._cancellations[job_id]
            worker_lock = DataLifecycleLock(self.root)
            try:
                # Separate control lock keeps multiple local API processes from
                # running model embedding/import work concurrently.
                while not worker_lock.try_acquire():
                    if cancel.wait(0.05):
                        break
                if self.is_cancelled(job_id):
                    cancel.set()
                job.update(status="running", message="Validating and importing files one at a time. AI answers and analyses are not generated during import.")
                self._persist(job)
                for entry in job["files"]:
                    if entry["status"] != "queued":
                        continue
                    if cancel.is_set() or (self._directory(job_id) / "cancel.request").is_file():
                        cancel.set()
                        break
                    # The short lock is shared with ordinary imports and reset.
                    # Never keep it while waiting for another file or user input.
                    lifecycle = DataLifecycleLock(self.data_dir)
                    try:
                        while not lifecycle.try_acquire():
                            if cancel.wait(0.05):
                                break
                        if cancel.is_set():
                            break
                        if generation_reader() != job.get("reset_generation"):
                            job["message"] = "Project data changed during import. Remaining files were cancelled to preserve the reset."
                            cancel.set()
                            break
                        entry["status"] = "processing"
                        self._persist(job)
                        staged = self._directory(job_id) / "staged" / entry["_path"]
                        if staged.is_symlink() or not staged.is_file() or staged.stat().st_size > job["limits"]["max_file_bytes"]:
                            raise BulkImportError("The staged file is unavailable or exceeds the size limit.")
                        result = processor(staged, entry["name"], entry["kind"], dict(options), approved_documents)
                        entry.update({key: value for key, value in result.items() if key in {"event_id", "document_id", "approved", "signal_count", "state_count", "log_count", "quality_status", "warnings"}})
                        entry["status"] = "imported"
                    except Exception as exc:
                        entry["status"] = "failed"
                        entry["error"] = str(exc)[:800] if isinstance(exc, (ValueError, BulkImportError)) else "This file could not be imported. Its original was not changed; check the file format and try it individually."
                    finally:
                        lifecycle.close()
                        if entry.get("_path"):
                            (self._directory(job_id) / "staged" / entry["_path"]).unlink(missing_ok=True)
                        self._persist(job)
                if cancel.is_set():
                    for entry in job["files"]:
                        if entry["status"] == "queued":
                            entry["status"] = "cancelled"
                    job["status"] = "cancelled"
                    if "reset" not in job["message"]:
                        job["message"] = "Import cancelled. Files that already finished remain saved."
                else:
                    job["status"] = "completed"
                    failures = sum(entry["status"] == "failed" for entry in job["files"])
                    job["message"] = f"Import finished. {failures} file(s) need attention." if failures else "Import finished. Original files are preserved; documents require explicit approval for AI retrieval."
            except Exception:
                job.update(status="failed", message="The bulk worker stopped unexpectedly. Completed files remain saved; add remaining files as a new batch.")
                for entry in job["files"]:
                    if entry["status"] in {"queued", "processing"}:
                        entry.update(status="failed", error="The bulk worker was interrupted before this file finished.")
            finally:
                try:
                    self._persist(job)
                    staged_dir = self._directory(job_id) / "staged"
                    if staged_dir.exists() and not staged_dir.is_symlink():
                        shutil.rmtree(staged_dir)
                finally:
                    worker_lock.close()
                    self._slots.release()
                    try:
                        with self._mutex:
                            self._pending.discard(job_id)
                            self._persist(job)
                    finally:
                        self._queue.task_done()


@lru_cache(maxsize=4)
def get_bulk_manager(data_dir: str) -> BulkImportManager:
    return BulkImportManager(Path(data_dir))
