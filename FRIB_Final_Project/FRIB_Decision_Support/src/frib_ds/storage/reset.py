"""Bounded reset cleanup and the lifecycle lock shared by API workers."""
from __future__ import annotations

import os
import errno
from pathlib import Path
import stat
import time


class UnsafeResetPath(ValueError):
    pass


def _not_link(path:Path)->os.stat_result:
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
        raise UnsafeResetPath("Reset refused: an event/document store contains a symbolic link, junction or reparse point. Move it outside the store before retrying.")
    return info


def owned_store_inventory(config,files,documents)->tuple[list[Path],list[Path]]:
    """Resolve exact roots and preflight the complete tree before any mutation.

    Parent OneDrive folders are allowed. App-owned roots and every descendant
    must be ordinary directories/files: cleanup never follows a reparse point.
    """
    data=Path(config.data_dir).resolve()
    roots=[Path(config.event_dir),Path(config.document_dir)]
    expected=[data/"events",data/"documents"]
    actual=[Path(files.event_dir),Path(documents.directory)]
    all_files=[]; all_dirs=[]
    for raw,wanted,store_root in zip(roots,expected,actual):
        if raw.name!=wanted.name or raw.parent.resolve()!=data:
            raise UnsafeResetPath("Reset refused: event/document store is outside the configured application data directory.")
        try: info=_not_link(raw)
        except FileNotFoundError: continue
        if not stat.S_ISDIR(info.st_mode) or raw.resolve()!=wanted or store_root.resolve()!=wanted:
            raise UnsafeResetPath("Reset refused: event/document store root is not its expected application-owned directory.")
        stack=[raw]
        while stack:
            directory=stack.pop()
            for entry in directory.iterdir():
                info=_not_link(entry)
                if not entry.resolve().is_relative_to(wanted):
                    raise UnsafeResetPath("Reset refused: a stored path escapes the application-owned directory.")
                if stat.S_ISDIR(info.st_mode):
                    stack.append(entry); all_dirs.append(entry)
                elif stat.S_ISREG(info.st_mode): all_files.append(entry)
                else: raise UnsafeResetPath("Reset refused: an event/document store contains a special filesystem object.")
    return all_files,all_dirs


def clear_owned_stores(config,files,documents)->None:
    stored,directories=owned_store_inventory(config,files,documents)
    roots={Path(config.event_dir).resolve(),Path(config.document_dir).resolve()}
    _clear_inventory(stored,directories,roots)


def _clear_inventory(stored,directories,roots):
    def verify_parents(path:Path):
        current=path
        while current not in roots:
            _not_link(current)
            if current.parent==current:
                raise UnsafeResetPath("Reset refused: cleanup path is outside its application-owned root.")
            current=current.parent
        _not_link(current)
    for path in stored:
        verify_parents(path)
        path.unlink()
    for path in sorted(directories,key=lambda item:len(item.parts),reverse=True):
        verify_parents(path)
        path.rmdir()


def legacy_index_inventory(config,vector)->tuple[list[Path],list[Path]]:
    """Inactive index files in data/chroma are app-owned uploaded content too.

    Retain the live SQLite DB after clearing its rows. A live Chroma collection
    must be cleared through its API, because it holds database/HNSW handles;
    only the inactive SQLite cosine index is removable in that provider mode.
    """
    data=Path(config.data_dir).resolve(); raw=Path(config.chroma_dir)
    wanted=data/"chroma"
    active=Path(vector.path).resolve() if hasattr(vector,"path") else None
    if active and (active==wanted or not active.is_relative_to(wanted)):
        raise UnsafeResetPath("Reset refused: the configured SQLite retrieval index is outside the application-owned data/chroma directory.")
    if raw.name!="chroma" or raw.parent.resolve()!=data:
        raise UnsafeResetPath("Reset refused: retrieval store is outside the configured application data directory.")
    try: info=_not_link(raw)
    except FileNotFoundError: return [],[]
    if not stat.S_ISDIR(info.st_mode) or raw.resolve()!=wanted:
        raise UnsafeResetPath("Reset refused: retrieval store root is not its expected application-owned directory.")
    files=[]; directories=[]; stack=[raw]
    while stack:
        directory=stack.pop()
        for entry in directory.iterdir():
            info=_not_link(entry)
            if not entry.resolve().is_relative_to(wanted):
                raise UnsafeResetPath("Reset refused: a retrieval path escapes its application-owned directory.")
            if stat.S_ISDIR(info.st_mode): stack.append(entry); directories.append(entry)
            elif stat.S_ISREG(info.st_mode): files.append(entry)
            else: raise UnsafeResetPath("Reset refused: retrieval store contains a special filesystem object.")
    if hasattr(vector,"collection"):
        return [path for path in files if path.parent==raw and path.name in {"vectors.sqlite","vectors.sqlite-wal","vectors.sqlite-shm","vectors.sqlite-journal"}],[]
    retained={active,*(Path(str(active)+suffix) for suffix in ("-wal","-shm","-journal"))} if active else set()
    return [path for path in files if path.resolve() not in retained],[path for path in directories if not active or not active.is_relative_to(path.resolve())]


def clear_legacy_indexes(config,vector)->None:
    stored,directories=legacy_index_inventory(config,vector)
    _clear_inventory(stored,directories,{Path(config.chroma_dir).resolve()})


class DataLifecycleLock:
    """OS file lock; protects whole data requests across local API workers.

    The one-byte control file contains no user data and is preserved on reset.
    Use try_acquire in async middleware to avoid consuming threadpool workers
    while another request is processing a large upload.
    """
    def __init__(self,data_dir:Path):
        self.path=Path(data_dir)/".lifecycle.lock"
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.is_symlink(): raise UnsafeResetPath("Lifecycle lock cannot be a symbolic link")
        self.stream=self.path.open("a+b")
        self.stream.seek(0,os.SEEK_END)
        if not self.stream.tell(): self.stream.write(b"\0"); self.stream.flush()
        self.locked=False

    def try_acquire(self)->bool:
        self.stream.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES,errno.EAGAIN,errno.EDEADLK}: return False
            raise
        self.locked=True
        return True

    def close(self):
        if self.locked:
            self.stream.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()

    def __enter__(self):
        while not self.try_acquire(): time.sleep(0.02)
        return self

    def __exit__(self,*_): self.close()
