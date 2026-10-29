"""Package the complete application beside portable, verified live-demo inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
ROOT = "FRIB_Final_Project"


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def cmd_bytes(text: str) -> bytes:
    return (text.strip().replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n").encode("ascii")


def build_bundle(output: Path) -> dict:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="frib-final-") as temporary:
        source_zip = Path(temporary) / "source.zip"
        subprocess.run([sys.executable, str(PROJECT / "scripts/package_project.py"), str(source_zip)], check=True, capture_output=True, text=True)
        with zipfile.ZipFile(source_zip) as source:
            for name in source.namelist():
                if not name.endswith("/"):
                    files[name] = source.read(name)

    manifest = json.loads((PROJECT / "sample_data/test_lab/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("fictional") is not True or manifest.get("schema_version") != "1.0":
        raise ValueError("A supported fictional fixture manifest is required.")
    counts = {}
    for kind, folder, allowed in (("datasets", "datasets", "sample_data/test_lab"), ("procedures", "procedures", "sample_docs/test_lab")):
        counts[kind] = len(manifest[kind])
        for entry in manifest[kind]:
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
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" %*
exit /b %ERRORLEVEL%
''')
    files["START_LIVE_DEMO.cmd"] = cmd_bytes(r'''
@echo off
setlocal
set "FRIB_CONFIG_DIR=%~dp0FRIB_Decision_Support\config"
set "FRIB_DATA_DIR=%~dp0Demo_Workspace"
set "FRIB_LLM_PROVIDER=mock"
set "FRIB_EMBEDDING_PROVIDER=hash"
set "FRIB_VECTOR_PROVIDER=sqlite"
echo Starting the fictional live demo in its separate Demo_Workspace folder.
echo Stop any previous FRIB launcher with Ctrl+C before starting this one.
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" %*
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
    files["READ_ME_FIRST.md"] = (
        "# FRIB final project and live demo\n\n"
        "Extract the entire ZIP into a writable folder before running it.\n\n"
        "1. For your presentation, double-click **START_LIVE_DEMO.cmd**. It checks and installs requirements and opens the app, using a separate **Demo_Workspace** for presentation records. First setup needs internet.\n"
        "2. Follow **Live_Demo_Data/README.md**. Upload inputs from **datasets** and **procedures**, or use the app's **Test Lab** presets. Files are fictional training inputs. Nothing is imported automatically.\n"
        "3. For normal use, double-click **START_FRIB.cmd**. Stop the previous launcher with **Ctrl+C** before switching; both use the same local ports. Keep the launcher window open while using the app.\n"
        "4. To check every supplied demo input, stop the app and double-click **RUN_DEMO_CHECKS.cmd**. It verifies the separate folder through 32 grouped API checks in disposable storage, then writes **Demo_Check_Results**.\n\n"
        "**FRIB_Decision_Support** contains the full source, configuration, tests, documentation and reference PDFs. "
        "**Live_Demo_Data** contains 13 datasets, 7 procedure files, import-setting references and the presenter guide. "
        "**Verification** contains the current packaging/demo verification result and prior full startup validation report.\n\n"
        "Required runtime downloads are handled by startup. Saved user uploads, virtual environments and private machine data are excluded. "
        "The default demo uses mock answers, hash retrieval and SQLite; large optional AI models are separate choices. "
        "Approving a fictional procedure is an explicit demonstration action, not facility approval.\n"
    ).encode("utf-8")
    files["READ_ME_FIRST.txt"] = files["READ_ME_FIRST.md"].decode("utf-8").replace("# ", "").replace("**", "").encode("utf-8")
    files["Verification/STARTUP_VALIDATION_REPORT.md"] = (PROJECT / "docs/STARTUP_VALIDATION_REPORT.md").read_bytes()
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
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(files.items()):
            archive.writestr(ROOT + "/" + name, contents)
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
