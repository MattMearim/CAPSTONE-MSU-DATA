"""Portable distributions retain Finder launchers and their Unix permissions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_EXECUTABLES = ("Start FRIB.command", "Setup Local AI.command", "Run Test Lab.command", "scripts/start_unix.sh", "Run Unit Tests.command", "Run Security Checks.command", "scripts/run_checks.sh")
BUNDLE_EXECUTABLES = ("START_FRIB.command", "START_LIVE_DEMO.command", "SETUP_LOCAL_AI.command", "RUN_DEMO_CHECKS.command", "RUN_UNIT_TESTS.command", "RUN_SECURITY_CHECKS.command")


def extract_with_permissions(archive: zipfile.ZipFile, destination: Path) -> None:
    archive.extractall(destination)
    for entry in archive.infolist():
        if not entry.is_dir():
            (destination / entry.filename).chmod((entry.external_attr >> 16) & 0o777)


def assert_executable(archive: zipfile.ZipFile, name: str) -> None:
    entry = archive.getinfo(name)
    assert entry.create_system == 3
    assert (entry.external_attr >> 16) & 0o111 == 0o111, name


def test_source_can_rebuild_complete_macos_bundle_without_original_parent(tmp_path):
    source_zip = tmp_path / "source.zip"
    subprocess.run([sys.executable, str(PROJECT / "scripts/package_project.py"), str(source_zip)], check=True, capture_output=True, text=True)
    with zipfile.ZipFile(source_zip) as archive:
        for name in SOURCE_EXECUTABLES:
            assert_executable(archive, "FRIB_Decision_Support/" + name)
        extract_with_permissions(archive, tmp_path / "source with spaces")
    extracted = tmp_path / "source with spaces/FRIB_Decision_Support"
    bundle_zip = tmp_path / "rebuilt.zip"
    rebuilt = subprocess.run([sys.executable, str(extracted / "scripts/package_final_bundle.py"), str(bundle_zip)], check=True, capture_output=True, text=True)
    assert json.loads(rebuilt.stdout)["saved_user_data_included"] is False
    with zipfile.ZipFile(bundle_zip) as archive:
        for name in BUNDLE_EXECUTABLES:
            assert_executable(archive, "FRIB_Final_Project/" + name)
        for name in SOURCE_EXECUTABLES:
            assert_executable(archive, "FRIB_Final_Project/FRIB_Decision_Support/" + name)
        assert b"START_LIVE_DEMO.command" in archive.read("FRIB_Final_Project/MACOS_SETUP.md")
        assert b"SETUP_LOCAL_AI.command" in archive.read("FRIB_Final_Project/MACOS_SETUP.md")
        for launcher in ("START_FRIB.command", "START_LIVE_DEMO.command", "START_FRIB.cmd", "START_LIVE_DEMO.cmd"):
            contents = archive.read("FRIB_Final_Project/" + launcher)
            assert b"--local-ai" in contents
            assert b"PROVIDER=mock" not in contents and b"PROVIDER=hash" not in contents
        assert b"Start tutorial" in archive.read("FRIB_Final_Project/FIRST_STEPS.md")
        assert archive.read("FRIB_Final_Project/FIRST_STEPS.md") == archive.read("FRIB_Final_Project/FRIB_Decision_Support/docs/FIRST_STEPS.md")
        assert "FRIB_Final_Project/FRIB_Decision_Support/src/frib_ds/dashboard/tutorial_ui.py" in archive.namelist()
        assert "FRIB_Final_Project/FRIB_Decision_Support/startup_window.py" in archive.namelist()
        checksums = archive.read("FRIB_Final_Project/SHA256SUMS.txt").decode("utf-8")
        for line in checksums.splitlines():
            checksum, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read("FRIB_Final_Project/" + name)).hexdigest() == checksum
        extract_with_permissions(archive, tmp_path / "final with spaces")

    bash = shutil.which("bash")
    if bash is None or os.name == "nt":
        pytest.skip("Executing Unix launchers requires a Unix host with Bash")
    bundle = tmp_path / "final with spaces/FRIB_Final_Project"
    # Capture the dispatch contract without installing runtimes or opening UI.
    runner = bundle / "FRIB_Decision_Support/scripts/start_unix.sh"
    runner.write_text("#!/bin/bash\n" + "exec \"$FRIB_TEST_PYTHON\" -c 'import json, os, sys; print(json.dumps({\"args\": sys.argv[1:], \"data\": os.getenv(\"FRIB_DATA_DIR\"), \"provider\": os.getenv(\"FRIB_LLM_PROVIDER\")})); sys.exit(int(os.getenv(\"FRIB_TEST_EXIT\", \"0\")))' \"$@\"\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(FRIB_NO_PAUSE="1", FRIB_TEST_PYTHON=sys.executable)
    for name in BUNDLE_EXECUTABLES:
        subprocess.run([bash, "-n", str(bundle / name)], check=True, capture_output=True, text=True)
    normal = subprocess.run([str(bundle / "START_FRIB.command"), "--check", "an argument with spaces"], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert normal.returncode == 0, normal.stderr
    assert json.loads(normal.stdout)["args"] == ["--local-ai", "--check", "an argument with spaces"]
    demo = subprocess.run([str(bundle / "START_LIVE_DEMO.command"), "--no-browser"], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert demo.returncode == 0, demo.stderr
    payload = json.loads(demo.stdout.splitlines()[-1])
    assert payload["args"] == ["--local-ai", "--no-browser"]
    assert payload["data"] == str(bundle / "Demo_Workspace_AI") and payload["provider"] == "ollama"
    setup = subprocess.run([str(bundle / "SETUP_LOCAL_AI.command")], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert setup.returncode == 0, setup.stderr
    assert json.loads(setup.stdout)["args"] == ["--setup-local-ai"]
    checks = subprocess.run([str(bundle / "RUN_DEMO_CHECKS.command"), "--verbose"], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert checks.returncode == 0, checks.stderr
    assert json.loads(checks.stdout)["args"] == ["--test-lab", "--manifest", str(bundle / "Live_Demo_Data/configuration/test_lab/manifest.json"), "--output", str(bundle / "Demo_Check_Results"), "--verbose"]
    environment["FRIB_TEST_EXIT"] = "7"
    failed = subprocess.run([str(bundle / "START_FRIB.command"), "--check"], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert failed.returncode == 7 and "exit code 7" in failed.stdout
