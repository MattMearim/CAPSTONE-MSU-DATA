"""Durable per-user AI assets shared by every extracted FRIB project."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import stat
import threading
import uuid


def ai_home(source=None):
    env = os.environ if source is None else source
    if env.get("FRIB_AI_HOME"):
        return Path(env["FRIB_AI_HOME"]).expanduser().absolute()
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/FRIB"
    if os.name == "nt":
        return Path(env.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "FRIB"
    return Path(env.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "FRIB"


def guard_path(path, source=None):
    root = ai_home(source)
    path = Path(path).expanduser().absolute()
    if ".." in root.parts:
        raise RuntimeError("FRIB_AI_HOME cannot contain parent traversal.")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Shared AI storage path is outside FRIB_AI_HOME.") from exc
    if ".." in relative.parts:
        raise RuntimeError("Shared AI storage paths cannot contain parent traversal.")
    paths = [*reversed(root.parents), root]
    paths.extend(root.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1))
    for current in paths:
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise RuntimeError("Refusing linked or redirected shared AI storage: " + str(current))
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError("Shared AI storage requires ordinary files and directories.")
    return path


def ensure_directory(path, source=None):
    path = guard_path(path, source)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    guard_path(path, source)
    return path


def atomic_json(path, payload, source=None):
    path = guard_path(path, source)
    ensure_directory(path.parent, source)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        guard_path(path, source)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_registry_guard = threading.Lock()
_registry = {}


class AIStorageLock:
    """Crash-released OS lock; reentrant for setup calling the runtime installer."""
    def __init__(self, source=None):
        self.source = source
        self.path = ai_home(source) / "setup.lock"
        self.entry = None

    def __enter__(self):
        ensure_directory(self.path.parent, self.source)
        guard_path(self.path, self.source)
        with _registry_guard:
            entry = _registry.setdefault(str(self.path), {"thread": threading.RLock(), "depth": 0, "stream": None})
        if not entry["thread"].acquire(blocking=False):
            raise RuntimeError("Another FRIB AI setup is already preparing shared models. Wait for it to finish.")
        try:
            if entry["depth"] == 0:
                stream = self.path.open("a+b")
                try:
                    stream.seek(0, os.SEEK_END)
                    if not stream.tell():
                        stream.write(b"\0")
                        stream.flush()
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except Exception as exc:
                    stream.close()
                    raise RuntimeError("Another FRIB AI setup is already preparing shared models. Wait for it to finish.") from exc
                entry["stream"] = stream
            entry["depth"] += 1
            self.entry = entry
            return self
        except BaseException:
            entry["thread"].release()
            raise

    def __exit__(self, *_args):
        entry = self.entry
        if entry is None:
            return
        try:
            entry["depth"] -= 1
            if entry["depth"] == 0:
                entry["stream"].close()
                entry["stream"] = None
        finally:
            self.entry = None
            entry["thread"].release()
