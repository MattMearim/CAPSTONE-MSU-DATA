"""Copy an existing workspace to a fresh semantic-AI workspace without overwriting it.

Run only while FRIB is stopped:
python -m frib_ds.migrate_semantic --source data --destination data-local-ai
The source remains the backup; only the copied catalog and retrieval index change.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from datetime import datetime, timezone
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import uuid

import yaml

from frib_ds.bootstrap import embedding_fingerprint
from frib_ds.rag.embeddings import HashEmbeddingProvider, build_embedding_provider
from frib_ds.rag.vector_store import SQLiteVectorStore
from frib_ds.storage.reset import DataLifecycleLock
from frib_ds.storage.sqlite import SQLiteRepository


PROJECT = Path(__file__).resolve().parents[2]


def _ordinary(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Migration refused a linked or redirected path: {path}")
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            raise ValueError(f"Migration refused a hardlinked file: {path}")
    elif not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"Migration requires ordinary files and directories: {path}")
    return info


def _inventory(root: Path):
    files = []
    stack = [root]
    while stack:
        directory = stack.pop()
        _ordinary(directory)
        for path in directory.iterdir():
            info = _ordinary(path)
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
            else:
                files.append((path, info))
    return files


def _models(config_dir: Path):
    path = config_dir / "models.yaml"
    _ordinary(path)
    models = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    llm = dict(models.get("llm", {}))
    embeddings = dict(models.get("embeddings", {}))
    vector = dict(models.get("vector_store", {}))
    llm["provider"] = os.getenv("FRIB_LLM_PROVIDER", llm.get("provider", "ollama"))
    embeddings["provider"] = os.getenv("FRIB_EMBEDDING_PROVIDER", embeddings.get("provider", "sentence_transformers"))
    embeddings["model"] = os.getenv("FRIB_EMBEDDING_MODEL", embeddings.get("model", "all-MiniLM-L6-v2"))
    if os.getenv("FRIB_EMBEDDING_CACHE"):
        embeddings["cache_folder"] = os.environ["FRIB_EMBEDDING_CACHE"]
    vector["provider"] = os.getenv("FRIB_VECTOR_PROVIDER", vector.get("provider", "sqlite"))
    if llm["provider"] not in {"ollama", "lmstudio"} or embeddings["provider"] != "sentence_transformers":
        raise ValueError("Semantic migration requires a real Ollama/LM Studio model and SentenceTransformers; mock/hash modes cannot migrate data.")
    if vector["provider"] != "sqlite" or vector.get("path"):
        raise ValueError("Semantic migration supports the standard SQLite vector store only; custom paths and Chroma require a separate reviewed migration.")
    return embeddings


def _copy_file(source: Path, target: Path, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as original:
        current = os.fstat(original.fileno())
        if (current.st_dev, current.st_ino, current.st_nlink, current.st_size, current.st_mtime_ns) != (
                expected.st_dev, expected.st_ino, 1, expected.st_size, expected.st_mtime_ns):
            raise ValueError("A source file changed while preparing migration; stop FRIB and retry.")
        with target.open("xb") as output:
            shutil.copyfileobj(original, output)
        after = os.fstat(original.fileno())
        if after.st_size != current.st_size or after.st_mtime_ns != current.st_mtime_ns:
            raise ValueError("A source file changed during migration; stop FRIB and retry.")


def _validate_vectors(chunks, vectors):
    if len(chunks) != len(vectors):
        raise ValueError("Semantic migration requires one embedding for every approved chunk.")
    dimension = None
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("Semantic model returned an empty or invalid vector.")
        try:
            invalid = any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) for value in vector)
        except (TypeError, ValueError, OverflowError):
            invalid = True
        if invalid or (dimension is not None and len(vector) != dimension):
            raise ValueError("Semantic model returned nonfinite values or inconsistent vector dimensions.")
        dimension = len(vector)
    return dimension


def _promote_directory(source: Path, destination: Path):
    """Atomic rename with no-replace semantics, including an empty raced target."""
    if os.name == "nt":
        os.rename(source, destination)  # Windows rejects an existing destination.
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError("This platform cannot safely promote a migration without overwriting a raced destination.")
    if result:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(destination))


def migrate_semantic(source: str | Path, destination: str | Path, config_dir: str | Path | None = None):
    configuration = Path(config_dir or os.getenv("FRIB_CONFIG_DIR", PROJECT / "config")).absolute()
    _ordinary(configuration)
    project = configuration.parent.resolve()
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    for path in (source, destination):
        if path.parent.resolve() != project or not re.fullmatch(r"data(?:[-_][A-Za-z0-9_-]+)?", path.name):
            raise ValueError("Migration data folders must be ordinary, distinct data folders directly inside this project.")
    _ordinary(source)
    if not source.is_dir() or source == destination:
        raise ValueError("Choose an existing source data folder and a different new destination.")
    if os.path.lexists(destination):
        raise FileExistsError("Migration never overwrites an existing destination: " + str(destination))
    database = source / "frib.db"
    if not stat.S_ISREG(_ordinary(database).st_mode):
        raise ValueError("The source has no ordinary FRIB catalog database.")
    settings = _models(configuration)
    # Preflight the whole source, including inactive indexes, before a lock or copy.
    _inventory(source)
    lock = DataLifecycleLock(source)
    staging = None
    try:
        if not lock.try_acquire():
            raise RuntimeError("FRIB is using the source workspace. Stop it before migrating.")
        files = _inventory(source)
        _ordinary(database)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as original:
            pending = original.execute("SELECT value FROM repository_metadata WHERE key='reset_pending'").fetchone()
            if pending:
                raise ValueError("A data reset is pending. Finish that reset before migrating.")
            staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-migrating-", dir=project))
            for name in ("events", "documents", "logs"):
                if (source / name).is_dir():
                    (staging / name).mkdir()
            for path, info in files:
                relative = path.relative_to(source)
                if relative.parts[0] == "chroma" or (len(relative.parts) == 1 and (
                        relative.name in {".lifecycle.lock", "frib.db", "frib.db-wal", "frib.db-shm", "frib.db-journal"})):
                    continue
                _copy_file(path, staging / relative, info)
            with closing(sqlite3.connect(staging / "frib.db")) as copied:
                original.backup(copied)
        repo = SQLiteRepository(staging / "frib.db")
        if repo.pending_reset():
            raise ValueError("The copied workspace has a pending reset; migration was cancelled.")
        provider = build_embedding_provider(settings)
        if isinstance(provider, HashEmbeddingProvider):
            raise ValueError("Hash embeddings cannot be used for semantic migration.")
        rows = repo.approved_document_chunks()
        chunks = [chunk for chunk, _vector in rows]
        if any(not chunk.approved for chunk in chunks):
            raise ValueError("The approved document catalog contains an inconsistent chunk approval.")
        vectors = provider.embed([chunk.text for chunk in chunks]) if chunks else []
        dimension = _validate_vectors(chunks, vectors)
        fingerprint = embedding_fingerprint(settings)
        with repo.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany("UPDATE document_chunks SET vector=? WHERE chunk_id=?", [
                (json.dumps(vector, allow_nan=False), chunk.chunk_id) for chunk, vector in zip(chunks, vectors)])
            connection.execute("INSERT OR REPLACE INTO repository_metadata VALUES('embedding_fingerprint',?)",
                               (json.dumps(fingerprint, sort_keys=True, separators=(",", ":")),))
            connection.execute("INSERT OR REPLACE INTO repository_metadata VALUES('documents_generation',?)", (uuid.uuid4().hex,))
        store = SQLiteVectorStore(staging / "chroma" / "vectors.sqlite")
        store.add(chunks, vectors)
        if store.count() != len(chunks):
            raise RuntimeError("The semantic retrieval index did not retain every approved chunk.")
        repo.ensure_embedding_compatibility(fingerprint)
        with repo.connect() as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("The migrated catalog failed SQLite integrity validation.")
        receipt = {"schema_version": "1.0", "migration_id": "SEMANTIC-" + uuid.uuid4().hex,
                   "completed_at": datetime.now(timezone.utc).isoformat(), "source": str(source),
                   "destination": str(destination), "source_preserved": True,
                   "embedding_fingerprint": fingerprint, "approved_chunks_reembedded": len(chunks),
                   "vector_dimensions": dimension, "copied_data_counts": repo.data_counts(),
                   "index_policy": "Only approved catalog chunks were reembedded into a fresh SQLite index; old retrieval index files were omitted from the copy."}
        (staging / "SEMANTIC_MIGRATION.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        _promote_directory(staging, destination)
        staging = None
        return receipt
    finally:
        lock.close()
        if staging is not None:
            shutil.rmtree(staging)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path)
    args = parser.parse_args(arguments)
    try:
        receipt = migrate_semantic(args.source, args.destination, args.config_dir)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"Semantic migration did not complete: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
