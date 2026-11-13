"""Package the complete application beside portable, verified live-demo inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
ROOT = "FRIB_Final_Project"


def archive_member(name: str) -> str:
    """Portable ZIP names cannot target another folder or Windows stream."""
    if (not isinstance(name, str) or not name or any(character in name for character in ("\\", ":", "\0"))
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("An archive member must be a plain relative path.")
    return name


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def cmd_bytes(text: str) -> bytes:
    return (text.strip().replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n").encode("ascii")


def macos_launcher(setup: str = "", arguments: str = '"$@"') -> bytes:
    """Generate a portable Finder launcher without relying on a bundle parent."""
    return ('''#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
''' + setup + '''"$ROOT/FRIB_Decision_Support/scripts/start_unix.sh" ''' + arguments + '''
status=$?
if [ "$status" -ne 0 ]; then
    echo "FRIB stopped with exit code $status. See the message above and FRIB_Decision_Support/.frib/setup.log."
fi
if [ -t 0 ] && [ "${FRIB_NO_PAUSE:-0}" != 1 ]; then
    read -r -p "Press Return to close this window..." _
fi
exit "$status"
''').encode("utf-8")


def build_bundle(output: Path) -> dict:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="frib-final-") as temporary:
        source_zip = Path(temporary) / "source.zip"
        subprocess.run([sys.executable, str(PROJECT / "scripts/package_project.py"), str(source_zip)], check=True, capture_output=True, text=True)
        with zipfile.ZipFile(source_zip) as source:
            for entry in source.infolist():
                if not entry.is_dir():
                    archive_member(entry.filename)
                    files[entry.filename] = source.read(entry)
                    modes[entry.filename] = entry.external_attr >> 16

    manifest = json.loads((PROJECT / "sample_data/test_lab/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("fictional") is not True or manifest.get("schema_version") != "1.0":
        raise ValueError("A supported fictional fixture manifest is required.")
    counts = {}
    for kind, folder, allowed in (("datasets", "datasets", "sample_data/test_lab"), ("procedures", "procedures", "sample_docs/test_lab")):
        counts[kind] = len(manifest[kind])
        for entry in manifest[kind]:
            if not isinstance(entry.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", entry["id"]):
                raise ValueError("Demo input IDs must be plain identifiers without path components.")
            archive_member(folder + "/" + entry["filename"])
            source_path = (PROJECT / entry["path"]).resolve()
            if not source_path.is_relative_to((PROJECT / allowed).resolve()) or source_path.name != entry["filename"]:
                raise ValueError("A demo input path is outside its curated source folder.")
            contents = source_path.read_bytes()
            if digest(contents) != entry["sha256"] or len(contents) != entry["size_bytes"]:
                raise ValueError("Demo input integrity mismatch: " + entry["id"])
            entry["path"] = folder + "/" + entry["filename"]
            target = "Live_Demo_Data/" + entry["path"]
            if target in files:
                raise ValueError("Duplicate demo filename: " + target)
            files[target] = contents
            if kind == "datasets":
                settings = {"fictional": True, "dataset_id": entry["id"], "filename": entry["filename"], "title": entry["title"],
                    "import_kind": entry["import_kind"], "options": entry["options"],
                    "expected_outcome": entry["expected_outcome"], "expected": entry["expected"],
                    "question": entry.get("question"), "expected_issue_codes": entry.get("expected_issue_codes", []),
                    "note": "Reference mapping and expected outcomes. General upload does not automatically read this sidecar. Test Lab provides the preset mapping; repairs require explicit selection."}
                files["Live_Demo_Data/import_options/" + entry["id"] + ".json"] = (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    # The existing runner derives its pack root from the manifest's two parent
    # folders. Keep that portable contract while presenting flat input folders.
    files["Live_Demo_Data/configuration/test_lab/manifest.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    files["Live_Demo_Data/README.md"] = (PROJECT / "docs/LIVE_DEMO_GUIDE.md").read_bytes()
    files["Live_Demo_Data/FEATURE_DETAILS.md"] = (PROJECT / "docs/TEST_LAB.md").read_bytes()
    files["Live_Demo_Data/import_options/README.md"] = (
        "# Import mapping reference\n\nEach JSON sidecar records the matching dataset's intended mapping, quality expectations and expected results. "
        "These files are reference material, not datasets or procedure uploads. Test Lab already supplies these settings. "
        "General Data workspace uploads require you to enter any desired mappings/expectations explicitly. "
        "The REPAIR sidecar describes a reviewed repair under `expected.repair_options`; the raw default import remains blocked. "
        "Native mechanical JSON uses event import and has no mixed-data mapping.\n"
    ).encode("utf-8")
    files["START_FRIB.cmd"] = cmd_bytes(r'''
@echo off
setlocal
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --local-ai %*
exit /b %ERRORLEVEL%
''')
    files["START_LIVE_DEMO.cmd"] = cmd_bytes(r'''
@echo off
setlocal
set "FRIB_CONFIG_DIR=%~dp0FRIB_Decision_Support\config"
set "FRIB_DATA_DIR=%~dp0Demo_Workspace_AI"
set "FRIB_LLM_PROVIDER=ollama"
set "FRIB_LLM_MODEL=qwen3:8b"
set "FRIB_EMBEDDING_PROVIDER=sentence_transformers"
set "FRIB_EMBEDDING_MODEL=all-MiniLM-L6-v2"
set "FRIB_VECTOR_PROVIDER=sqlite"
echo Starting fictional data with real local AI in Demo_Workspace_AI.
echo Stop any previous FRIB launcher with Ctrl+C before starting this one.
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --local-ai %*
exit /b %ERRORLEVEL%
''')
    files["RUN_DEMO_CHECKS.cmd"] = cmd_bytes(r'''
@echo off
setlocal
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --test-lab --manifest "%~dp0Live_Demo_Data\configuration\test_lab\manifest.json" --output "%~dp0Demo_Check_Results"
set "FRIB_EXIT=%ERRORLEVEL%"
if "%FRIB_EXIT%"=="0" echo All live-demo checks passed. Read Demo_Check_Results\TEST_LAB_RESULTS.md.
if not "%FRIB_EXIT%"=="0" echo Checks did not finish successfully. Read the explanation above.
pause
exit /b %FRIB_EXIT%
''')
    files["START_FRIB.command"] = macos_launcher(arguments='--local-ai "$@"')
    files["START_LIVE_DEMO.command"] = macos_launcher('''export FRIB_CONFIG_DIR="$ROOT/FRIB_Decision_Support/config"
export FRIB_DATA_DIR="$ROOT/Demo_Workspace_AI"
export FRIB_LLM_PROVIDER=ollama
export FRIB_LLM_MODEL=qwen3:8b
export FRIB_EMBEDDING_PROVIDER=sentence_transformers
export FRIB_EMBEDDING_MODEL=all-MiniLM-L6-v2
export FRIB_VECTOR_PROVIDER=sqlite
echo "Starting fictional data with real local AI in Demo_Workspace_AI."
''', arguments='--local-ai "$@"')
    files["SETUP_LOCAL_AI.command"] = macos_launcher(arguments='--setup-local-ai "$@"')
    files["RUN_DEMO_CHECKS.command"] = macos_launcher(arguments='--test-lab --manifest "$ROOT/Live_Demo_Data/configuration/test_lab/manifest.json" --output "$ROOT/Demo_Check_Results" "$@"')
    for name in ("START_FRIB.command", "START_LIVE_DEMO.command", "SETUP_LOCAL_AI.command", "RUN_DEMO_CHECKS.command"):
        modes[name] = stat.S_IFREG | 0o755
    for name, source in (("RUN_UNIT_TESTS.command", "Run Unit Tests.command"), ("RUN_SECURITY_CHECKS.command", "Run Security Checks.command")):
        files[name] = ("#!/bin/bash\nROOT=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\nexec \"$ROOT/FRIB_Decision_Support/" + source + "\" \"$@\"\n").encode("utf-8")
        modes[name] = stat.S_IFREG | 0o755
    files["MACOS_SETUP.md"] = (PROJECT / "docs/MACOS_SETUP.md").read_bytes()
    files["READ_ME_FIRST.md"] = (PROJECT / "docs/READ_ME_FIRST.md").read_bytes()
    files["READ_ME_FIRST.txt"] = files["READ_ME_FIRST.md"].decode("utf-8").replace("# ", "").replace("**", "").encode("utf-8")
    beginner_guide = PROJECT / "docs/FIRST_STEPS.md"
    if beginner_guide.is_file():
        files["FIRST_STEPS.md"] = beginner_guide.read_bytes()
    interface_guide = PROJECT / "docs/UI_WORKFLOW_GUIDE.md"
    if interface_guide.is_file():
        files["UI_GUIDE.md"] = interface_guide.read_bytes()
    bulk_guide = PROJECT / "docs/BULK_IMPORT_GUIDE.md"
    if bulk_guide.is_file():
        files["BULK_IMPORT_GUIDE.md"] = bulk_guide.read_bytes()
    files["Verification/STARTUP_VALIDATION_REPORT.md"] = (PROJECT / "docs/STARTUP_VALIDATION_REPORT.md").read_bytes()
    for name in ("REAL_AI_SETUP_REPORT.md", "REAL_AI_VALIDATION.json"):
        report = PROJECT / "docs" / name
        if report.is_file():
            files["Verification/" + name] = report.read_bytes()
    validation_report = PROJECT / "docs/FINAL_BUNDLE_VALIDATION.md"
    if validation_report.is_file():
        files["Verification/FINAL_BUNDLE_VALIDATION.md"] = validation_report.read_bytes()
    demo_results = PROJECT / "docs/LIVE_DEMO_CHECK_RESULTS.md"
    if demo_results.is_file():
        files["Verification/LIVE_DEMO_RESULTS.md"] = demo_results.read_bytes()
    metadata = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
                "fictional_demo_inputs": True, "counts": counts, "source_files": sum(name.startswith("FRIB_Decision_Support/") for name in files),
                "demo_manifest": "Live_Demo_Data/configuration/test_lab/manifest.json", "saved_user_data_included": False}
    files["BUNDLE_INFO.json"] = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
    checksums = "".join(f"{digest(contents)}  {name}\n" for name, contents in sorted(files.items()))
    files["SHA256SUMS.txt"] = checksums.encode("utf-8")
    # Validate the entire set before writing. Manifest IDs also become sidecar
    # names; checking only the source paths leaves those archive paths exposed.
    for name in files:
        archive_member(name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(files.items()):
            entry = zipfile.ZipInfo(ROOT + "/" + name)
            entry.create_system = 3
            entry.external_attr = modes.get(name, stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, contents)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise RuntimeError("Final archive CRC verification failed.")
        for name, contents in files.items():
            if digest(archive.read(ROOT + "/" + name)) != digest(contents):
                raise RuntimeError("Final archive integrity mismatch: " + name)
        for name in archive.namelist():
            if any(part in {".venv", ".frib", "data", "data-local-ai", "tmp", "__pycache__", ".pytest_cache"} for part in Path(name).parts):
                raise RuntimeError("Excluded runtime or saved data found in final bundle: " + name)
    output.with_suffix(output.suffix + ".sha256").write_text(digest(output.read_bytes()) + "  " + output.name + "\n", encoding="utf-8")
    return {**metadata, "archive_files": len(files), "size_bytes": output.stat().st_size, "sha256": digest(output.read_bytes()), "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.output), indent=2))


if __name__ == "__main__":
    main()
