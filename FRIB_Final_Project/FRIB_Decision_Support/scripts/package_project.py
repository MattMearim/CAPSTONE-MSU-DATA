"""Create and verify a portable source distribution without runtime or private data."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import stat
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {".github", "config", "contracts", "docs", "prompts", "sample_docs", "sample_data", "scripts", "src", "tests"}
SOURCE_FILES = {"pyproject.toml", "README.md", "START_HERE.md", "MACOS_SETUP.md", "start.py", "startup_window.py", "Start FRIB.cmd", "Run Test Lab.cmd", "Start FRIB.command", "Setup Local AI.command", "Run Test Lab.command", "Run Unit Tests.command", "Run Security Checks.command", "Dockerfile.backend", "Dockerfile.dashboard", "docker-compose.yml", "Makefile", ".gitignore", ".dockerignore", ".env.demo", ".env.example", "requirements-tested.txt"}


def included(relative: Path) -> bool:
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        return False
    if any(part in {"__pycache__", ".pytest_cache", ".venv", ".frib", "node_modules"} or part.endswith(".egg-info") for part in relative.parts):
        return False
    # Only the explicitly named root examples may contain environment settings.
    # Credentials and editor/cloud metadata can otherwise hide under docs/src.
    if any(part.startswith(".") for part in relative.parts):
        return len(relative.parts) == 1 and relative.name in SOURCE_FILES or relative.as_posix() in {".streamlit/config.toml", ".github/workflows/checks.yml"}
    if relative.name.lower() in {"secrets.toml", "credentials.json", "credentials.ini", "id_rsa", "id_ed25519"}:
        return False
    if relative.suffix.lower() in {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".zip"}:
        return False
    return (len(relative.parts) == 1 and relative.name in SOURCE_FILES) or relative.parts[0] in SOURCE_DIRS or relative.as_posix() in {".streamlit/config.toml", ".github/workflows/checks.yml"}


def checked_source(path: Path) -> Path:
    """Never publish a redirected file or a linked private file as source."""
    path = path.absolute()
    try:
        relative = path.relative_to(PROJECT.resolve())
    except ValueError as exc:
        raise ValueError("A source file is outside the project folder.") from exc
    if not relative.parts:
        raise ValueError("A source file must be a file inside the project folder.")
    current = PROJECT.resolve()
    for part in relative.parts:
        current /= part
        details = current.lstat()
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("Refusing a redirected source file: " + relative.as_posix())
    if not stat.S_ISREG(details.st_mode) or details.st_nlink > 1:
        raise ValueError("Source files must be ordinary, unlinked files: " + relative.as_posix())
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [PROJECT / name for name in SOURCE_FILES if (PROJECT / name).is_file()]
    files.append(PROJECT / ".streamlit/config.toml")
    for name in sorted(SOURCE_DIRS):
        directory = PROJECT / name
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*") if path.is_file() and included(path.relative_to(PROJECT)))
    # Preflight before creating the archive so a refusal cannot expose even a
    # partial private file. Recheck each path just before reading it as well.
    files = sorted(checked_source(path) for path in files)
    manifest = {}
    root = "FRIB_Decision_Support"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            checked_source(path)
            relative = path.relative_to(PROJECT).as_posix()
            contents = path.read_bytes()
            manifest[relative] = hashlib.sha256(contents).hexdigest()
            # Preserve executable macOS launchers while snapshotting bytes once.
            # Reopening via ZipFile.write could copy a different file if a
            # source changes between hashing and writing.
            entry = zipfile.ZipInfo(f"{root}/{relative}")
            entry.create_system = 3
            entry.external_attr = path.stat().st_mode << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, contents)
        checksums = "".join(f"{checksum}  {name}\n" for name, checksum in manifest.items())
        archive.writestr(f"{root}/SHA256SUMS.txt", checksums)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise RuntimeError("The project archive did not pass its integrity check")
        for relative, checksum in manifest.items():
            if hashlib.sha256(archive.read(f"{root}/{relative}")).hexdigest() != checksum:
                raise RuntimeError(f"Archive verification failed for {relative}")
        for required in ("start.py", "startup_window.py", "Start FRIB.cmd", "Start FRIB.command", "Run Test Lab.command", "Run Unit Tests.command", "Run Security Checks.command", "scripts/start_unix.sh", "scripts/bootstrap_windows.ps1", "config/models.yaml", ".streamlit/config.toml", "src/frib_ds/dashboard/app.py", "src/frib_ds/dashboard/system_ui.py", "docs/openapi.json"):
            if f"{root}/{required}" not in archive.namelist():
                raise RuntimeError(f"Missing required project file: {required}")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    print(f"Verified {len(files)} source files; {output.stat().st_size:,} bytes")
    print(output)


if __name__ == "__main__":
    main()
