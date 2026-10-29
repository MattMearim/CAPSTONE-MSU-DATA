"""Create and verify a portable source distribution without runtime or private data."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {"config", "contracts", "docs", "prompts", "sample_docs", "sample_data", "scripts", "src", "tests"}
SOURCE_FILES = {"pyproject.toml", "README.md", "START_HERE.md", "start.py", "Start FRIB.cmd", "Run Test Lab.cmd", "Dockerfile.backend", "Dockerfile.dashboard", "docker-compose.yml", "Makefile", ".gitignore", ".dockerignore", ".env.demo", ".env.example", "requirements-tested.txt"}


def included(relative: Path) -> bool:
    if any(part in {"__pycache__", ".pytest_cache", ".venv", ".frib", "node_modules"} or part.endswith(".egg-info") for part in relative.parts):
        return False
    if relative.suffix in {".pyc", ".pyo"}:
        return False
    return (len(relative.parts) == 1 and relative.name in SOURCE_FILES) or relative.parts[0] in SOURCE_DIRS or relative.as_posix() == ".streamlit/config.toml"


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
    files = sorted(files)
    manifest = {}
    root = "FRIB_Decision_Support"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(PROJECT).as_posix()
            contents = path.read_bytes()
            manifest[relative] = hashlib.sha256(contents).hexdigest()
            archive.writestr(f"{root}/{relative}", contents)
        checksums = "".join(f"{checksum}  {name}\n" for name, checksum in manifest.items())
        archive.writestr(f"{root}/SHA256SUMS.txt", checksums)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise RuntimeError("The project archive did not pass its integrity check")
        for relative, checksum in manifest.items():
            if hashlib.sha256(archive.read(f"{root}/{relative}")).hexdigest() != checksum:
                raise RuntimeError(f"Archive verification failed for {relative}")
        for required in ("start.py", "Start FRIB.cmd", "scripts/bootstrap_windows.ps1", "config/models.yaml", ".streamlit/config.toml", "src/frib_ds/dashboard/app.py", "src/frib_ds/dashboard/system_ui.py", "docs/openapi.json"):
            if f"{root}/{required}" not in archive.namelist():
                raise RuntimeError(f"Missing required project file: {required}")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    print(f"Verified {len(files)} source files; {output.stat().st_size:,} bytes")
    print(output)


if __name__ == "__main__":
    main()
