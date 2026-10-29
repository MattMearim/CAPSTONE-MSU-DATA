from pathlib import Path
import os
import subprocess
import sys
import json
import importlib.util
from types import SimpleNamespace

import pytest

from frib_ds.config import Config


PROJECT=Path(__file__).resolve().parents[1]


@pytest.fixture
def startup():
    spec = importlib.util.spec_from_file_location("isolated_frib_start", PROJECT / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configuration_works_outside_project_folder(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FRIB_DATA_DIR",str(tmp_path/"data"))
    monkeypatch.delenv("FRIB_CONFIG_DIR",raising=False)
    config=Config()
    assert config.config_dir==PROJECT/"config"
    assert config.prompts_dir==PROJECT/"prompts"
    assert config.scenario("plc_interlock")["duration_s"]>0


def test_standalone_generator_needs_no_ai_provider(tmp_path):
    env={**os.environ,"FRIB_LLM_PROVIDER":"unavailable-test-provider","FRIB_EMBEDDING_PROVIDER":"unavailable-test-provider","FRIB_VECTOR_PROVIDER":"unavailable-test-provider","FRIB_DATA_DIR":str(tmp_path/"data")}
    output=tmp_path/"plc.json"
    command=[sys.executable,str(PROJECT/"scripts/generate_event.py"),"plc","--seed","42","--output",str(output)]
    result=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    payload=output.read_bytes()
    assert json.loads(payload)["domain"]=="plc"
    again=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert again.returncode!=0
    assert output.read_bytes()==payload


def test_launcher_check_from_other_folder(tmp_path):
    result=subprocess.run([sys.executable,str(PROJECT/"start.py"),"--check"],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert "ready" in result.stdout


def test_environment_check_covers_every_required_distribution_and_import(startup):
    result = startup.check_environment(Path(sys.executable), PROJECT)
    assert result["ok"], result
    assert set(result["versions"]) == set(startup.IMPORTS) - {"httpx"}


def test_valid_uvicorn_environment_does_not_require_obsolete_colorama_extra(startup):
    # Recent Uvicorn standard extras no longer install colorama. The probe must
    # accept that layout instead of enforcing an obsolete Windows-only import.
    blocker = """
import importlib
original_import_module = importlib.import_module
def without_colorama(name, *args, **kwargs):
    if name == 'colorama':
        raise ModuleNotFoundError('colorama is not a current Uvicorn requirement')
    return original_import_module(name, *args, **kwargs)
importlib.import_module = without_colorama
"""
    checked = subprocess.run([startup.win_path(sys.executable), "-c", blocker + startup.PROBE,
        str(PROJECT), "0", json.dumps(startup.IMPORTS), json.dumps(startup.OPTIONAL_IMPORTS)],
        cwd=PROJECT, capture_output=True, text=True, timeout=30)
    assert checked.returncode == 0, checked.stderr
    result = json.loads(checked.stdout.strip().splitlines()[-1])
    assert result["ok"], result
    assert "uvicorn" in result["versions"]


def test_warm_environment_never_installs_or_checks_network(startup, tmp_path, monkeypatch):
    old = startup.environment_python(tmp_path / ".venv")
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "issues": []})
    monkeypatch.setattr(startup, "stage_environment", lambda *args: pytest.fail("Warm startup must not stage packages"))
    monkeypatch.setattr(startup, "ensure_stopped", lambda *args: pytest.fail("A read-only warm check needs no service shutdown"))
    assert startup.prepare_environment(tmp_path, ["--check"]) == old


def test_missing_environment_stages_and_switches_only_after_validation(startup, tmp_path, monkeypatch):
    replacement = tmp_path / ".frib/environments" / ("ENV-" + "a" * 32)
    python = startup.environment_python(replacement)
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": False, "issues": ["missing package"]})
    def staged(*args):
        assert not (tmp_path / ".frib/active-environment.json").exists()
        assert not startup.ProjectLock(tmp_path / ".frib/services.lock").acquire(), "Service starts must remain blocked while staging"
        return python, {"ok": True, "python_version": "3.13.16"}, {"validated_at": "test", "plan_id": None}
    monkeypatch.setattr(startup, "stage_environment", staged)
    assert startup.prepare_environment(tmp_path, ["--api-port", "54931", "--port", "54932"]) == python
    assert startup.active_python(tmp_path) == python
    assert json.loads((tmp_path / ".frib/last-upgrade.json").read_text())["status"] == "applied"


def test_failed_replacement_preserves_pointer_and_queue(startup, tmp_path, monkeypatch):
    pointer = tmp_path / ".frib/active-environment.json"
    startup.atomic_json(pointer, {"schema_version": "1.0", "path": "environments/ENV-" + "b" * 32})
    before = pointer.read_bytes()
    pending = tmp_path / ".frib/pending-upgrade.json"
    pending.write_text("queued", encoding="utf-8")
    monkeypatch.setattr(startup, "pending_upgrade", lambda *args: ({"plan_id": "test"}, b"queued"))
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": False, "issues": ["broken previous environment"]})
    def failed(*args): raise RuntimeError("Simulated network failure")
    monkeypatch.setattr(startup, "stage_environment", failed)
    with pytest.raises(RuntimeError, match="network"):
        startup.prepare_environment(tmp_path, ["--api-port", "54933", "--port", "54934"])
    assert pointer.read_bytes() == before
    assert pending.read_text() == "queued"
    guard = startup.ProjectLock(tmp_path / ".frib/services.lock")
    assert guard.acquire(); guard.close()


def test_failed_queued_upgrade_starts_healthy_previous_environment_for_cancellation(startup, tmp_path, monkeypatch, capsys):
    pointer = tmp_path / ".frib/active-environment.json"
    startup.atomic_json(pointer, {"schema_version": "1.0", "path": "environments/ENV-" + "c" * 32})
    previous = startup.active_python(tmp_path)
    pointer_before = pointer.read_bytes()
    pending = tmp_path / ".frib/pending-upgrade.json"
    pending.write_bytes(b"unchanged queued plan")
    receipt = tmp_path / ".frib/last-upgrade.json"
    failed_receipt = {"status": "failed", "error": "Simulated network failure", "previous_environment_retained": True}
    monkeypatch.setattr(startup, "pending_upgrade", lambda *args: ({"plan_id": "test"}, pending.read_bytes()))
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "python_version": "3.13.16"})
    def failed(*args):
        startup.atomic_json(receipt, failed_receipt)
        raise RuntimeError("Simulated network failure")
    monkeypatch.setattr(startup, "stage_environment", failed)
    selected = startup.prepare_environment(tmp_path, ["--api-port", "54935", "--port", "54936"])
    assert selected == previous
    assert pointer.read_bytes() == pointer_before
    assert pending.read_bytes() == b"unchanged queued plan"
    assert json.loads(receipt.read_text()) == failed_receipt
    output = capsys.readouterr().out
    assert "Queued upgrade failed" in output and "System & upgrades > Startup plan" in output
    guard = startup.ProjectLock(tmp_path / ".frib/services.lock")
    assert guard.acquire(); guard.close()


def test_repair_failure_never_falls_back_without_queued_plan(startup, tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": False, "issues": ["required package missing"]})
    def failed(*args):
        raise RuntimeError("Simulated first-install failure")
    monkeypatch.setattr(startup, "stage_environment", failed)
    with pytest.raises(RuntimeError, match="first-install"):
        startup.prepare_environment(tmp_path, ["--api-port", "54937", "--port", "54938"])
    assert not (tmp_path / ".frib/active-environment.json").exists()


def test_running_owned_services_block_package_changes(startup, tmp_path, monkeypatch):
    guard = startup.ProjectLock(tmp_path / ".frib/services.lock")
    assert guard.acquire()
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": False, "issues": ["repair"]})
    monkeypatch.setattr(startup, "stage_environment", lambda *args: pytest.fail("Do not install while services run"))
    try:
        with pytest.raises(RuntimeError, match="Ctrl.C"):
            startup.prepare_environment(tmp_path, [])
    finally: guard.close()


@pytest.mark.parametrize("relative", ["../outside", "environments/arbitrary", "C:/outside", "environments/ENV-" + "a" * 31])
def test_pointer_cannot_select_arbitrary_interpreter(startup, tmp_path, relative):
    startup.atomic_json(tmp_path / ".frib/active-environment.json", {"schema_version": "1.0", "path": relative})
    with pytest.raises(RuntimeError, match="pointer"):
        startup.active_python(tmp_path)


@pytest.mark.parametrize("payload", [[], None, 3, "not an object"])
def test_corrupted_pointer_shapes_have_actionable_errors(startup, tmp_path, payload):
    startup.atomic_json(tmp_path / ".frib/active-environment.json", payload)
    with pytest.raises(RuntimeError, match="pointer.*JSON object"):
        startup.active_python(tmp_path)


@pytest.mark.parametrize("arguments", [["--port", "99999"], ["--port", "-1"], ["--port", "invalid"], ["--port"], ["--port", "8000"]])
def test_invalid_ports_block_repair_and_release_service_guard(startup, tmp_path, arguments):
    with pytest.raises(RuntimeError, match="port"):
        startup.ensure_stopped(tmp_path, arguments)
    lock = startup.ProjectLock(tmp_path / ".frib/services.lock")
    assert lock.acquire()
    lock.close()


def test_reparse_path_refused_before_setup_writes(startup, tmp_path, monkeypatch):
    root = tmp_path / ".frib"
    root.mkdir()
    real_lstat = Path.lstat
    def fake_lstat(path):
        if path == root: return SimpleNamespace(st_file_attributes=0x400, st_nlink=1, st_mode=real_lstat(path).st_mode)
        return real_lstat(path)
    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(RuntimeError, match="redirected"):
        startup.atomic_json(root / "active-environment.json", {"path": "do not write"})
    assert not (root / "active-environment.json").exists()


def test_package_snapshot_preserves_dev_and_optional_dependencies(startup, tmp_path, monkeypatch):
    output = "# Editable project\n-e " + str(tmp_path) + "\npip==26.2.1\nsetuptools==80.0.0\npytest==9.1.1\nchromadb==1.0.0\nsentence-transformers==3.0.0\n"
    monkeypatch.setattr(startup.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""))
    assert startup.freeze_requirements("python", tmp_path) == ["pytest==9.1.1", "chromadb==1.0.0", "sentence-transformers==3.0.0"]


@pytest.mark.parametrize("requirement", ["package @ https://untrusted.invalid/file.whl", "--index-url https://untrusted.invalid", "-e C:/external"])
def test_package_snapshot_never_turns_external_commands_or_urls_into_pip_args(startup, tmp_path, monkeypatch, requirement):
    monkeypatch.setattr(startup.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=requirement, stderr=""))
    with pytest.raises(RuntimeError, match="external"):
        startup.freeze_requirements("python", tmp_path)


def test_failed_candidate_validation_keeps_old_environment_and_records_log(startup, tmp_path, monkeypatch):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(startup.subprocess, "run", run)
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": False, "issues": ["version conflict"]})
    with pytest.raises(RuntimeError, match="previous environment"):
        startup.stage_environment(tmp_path, tmp_path / "missing-python")
    receipt = json.loads((tmp_path / ".frib/last-upgrade.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["previous_environment_retained"] is True
    assert receipt["log_path"].endswith("setup.log")
    assert not (tmp_path / ".frib/active-environment.json").exists()
    assert all("missing-python" not in command[0] for command in commands)
    assert not any("sentence-transformers" in argument or "chromadb" in argument for command in commands for argument in command)


def test_test_lab_uses_active_interpreter_without_starting_services(startup, tmp_path, monkeypatch):
    selected = tmp_path / "active python.exe"
    calls = []
    monkeypatch.setattr(startup, "prepare_environment", lambda *args: selected)
    monkeypatch.setattr(startup.subprocess, "Popen", lambda command, **kwargs: calls.append(command) or SimpleNamespace(wait=lambda: 0))
    assert startup.main(["--test-lab", "--output", "folder with spaces"]) == 0
    assert calls == [[startup.win_path(selected), startup.win_path(PROJECT / "scripts/run_test_lab.py"), "--output", "folder with spaces"]]


def test_powershell_bootstrap_is_parseable_and_pins_official_runtime():
    source = PROJECT / "scripts/bootstrap_windows.ps1"
    text = source.read_text()
    assert "https://www.python.org/ftp/python/" in text
    assert "SHA256]::Create" in text and "Get-AuthenticodeSignature" in text
    assert "$env:PSModulePath = $PSHOME + '\\Modules'" in text
    assert "System32\\tar.exe" in text
    assert "Test-UsablePython $Executable @() $runtimeVersion" in text
    assert "bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159" in text
    assert "49b24a002efcf7451fe47a52ad9bc57a012a0c987eb6a635973ede200c421044" in text
    assert "Start-Process" not in text  # Runtime extraction does not invoke MSI/global installers.
    if os.name == "nt":
        script_path = str(source).replace("'", "''")
        command = "$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + script_path + "',[ref]$null,[ref]$errors) | Out-Null; if ($errors.Count) {$errors | Out-String | Write-Error; exit 1}"
        checked = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
        assert checked.returncode == 0, checked.stderr


def test_missing_pip_can_snapshot_installed_packages_with_stdlib(startup, tmp_path, monkeypatch):
    responses = iter([
        SimpleNamespace(returncode=1, stdout="", stderr="No module named pip"),
        SimpleNamespace(returncode=0, stdout=json.dumps([{"name": "numpy", "version": "2.3.0", "direct": None},
            {"name": "pytest", "version": "9.1.1", "direct": None}]), stderr="")])
    monkeypatch.setattr(startup.subprocess, "run", lambda *args, **kwargs: next(responses))
    assert startup.freeze_requirements("python", tmp_path) == ["numpy==2.3.0", "pytest==9.1.1"]


@pytest.mark.parametrize("upgrade_python", [False, True])
def test_staging_preserves_active_runtime_and_resolves_cross_python_wheels(startup, tmp_path, monkeypatch, upgrade_python):
    if upgrade_python and os.name != "nt":
        pytest.skip("Verified private runtime upgrades are Windows-only")
    current = startup.environment_python(tmp_path / "active")
    current.parent.mkdir(parents=True); current.touch()
    private = tmp_path / ".frib/python/3.13.16/python.exe"
    private.parent.mkdir(parents=True); private.touch()
    plan = {"upgrade_python": upgrade_python, "python_runtime": "3.13.16" if upgrade_python else "keep", "plan_id": "test", "components": ["numpy"]}
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            Path(command[3]).mkdir(parents=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(startup.subprocess, "run", run)
    monkeypatch.setattr(startup, "freeze_requirements", lambda *args: ["numpy==1.26.0", "scipy==1.13.0", "pytest==9.1.1"])
    monkeypatch.setattr(startup, "plan_tools", lambda *args: SimpleNamespace(build_install_requirements=lambda plan: ["numpy>=2.0"]))
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "versions": {}, "python_version": "3.13.16"})
    source_version = "3.11.9" if upgrade_python else "3.13.16"
    python, _, receipt = startup.stage_environment(tmp_path, current, plan, False, source_version)
    assert commands[0][0] == startup.win_path(private if upgrade_python else current), "Package-only updates must keep the active Python, not an old bootstrap interpreter"
    assert commands[0][3] == startup.win_path(python.parent.parent)
    assert commands[0][4] == "--without-pip"
    assert commands[1] == [startup.win_path(python), "-m", "ensurepip", "--upgrade", "--default-pip"]
    previous = python.parent.parent / "previous-packages.txt"
    assert previous.read_text().splitlines() == (["scipy", "pytest"] if upgrade_python else ["scipy==1.13.0", "pytest==9.1.1"])
    assert receipt.get("cross_python_resolution", False) is upgrade_python


def test_failed_dependency_probe_still_preserves_verified_active_python(startup, tmp_path, monkeypatch):
    current = startup.environment_python(tmp_path / "active")
    current.parent.mkdir(parents=True); current.touch()
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "-c":
            return SimpleNamespace(returncode=0, stdout="3.13.16\n")
        if command[1:3] == ["-m", "venv"]:
            Path(command[3]).mkdir(parents=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(startup.subprocess, "run", run)
    monkeypatch.setattr(startup, "freeze_requirements", lambda *args: [])
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "python_version": "3.13.16"})
    startup.stage_environment(tmp_path, current)
    assert commands[1][0] == startup.win_path(current)
    assert commands[1][1:3] == ["-m", "venv"]


@pytest.mark.skipif(os.name != "nt", reason="Verified private runtime upgrades are Windows-only")
def test_wrong_fixed_python_version_cannot_be_activated(startup, tmp_path, monkeypatch):
    private = tmp_path / ".frib/python/3.13.16/python.exe"
    private.parent.mkdir(parents=True); private.touch()
    def run(command, **kwargs):
        if command[1:3] == ["-m", "venv"]:
            Path(command[3]).mkdir(parents=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(startup.subprocess, "run", run)
    monkeypatch.setattr(startup, "plan_tools", lambda *args: SimpleNamespace(build_install_requirements=lambda plan: []))
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "python_version": "3.13.0"})
    plan = {"upgrade_python": True, "python_runtime": "3.13.16", "plan_id": "test", "components": []}
    with pytest.raises(RuntimeError, match="does not match.*3.13.16"):
        startup.stage_environment(tmp_path, tmp_path / "missing-python", plan)
    receipt = json.loads((tmp_path / ".frib/last-upgrade.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["previous_environment_retained"] is True
    assert not (tmp_path / ".frib/active-environment.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length paths")
@pytest.mark.parametrize("value,expected", [
    (r"C:\folder with spaces\python.exe", r"\\?\C:\folder with spaces\python.exe"),
    (r"\\server\share\python.exe", r"\\?\UNC\server\share\python.exe"),
    (r"\\?\C:\already extended\python.exe", r"\\?\C:\already extended\python.exe"),
    (r"\\?\UNC\server\share\python.exe", r"\\?\UNC\server\share\python.exe"),
])
def test_extended_paths_are_unc_safe_and_idempotent(startup, value, expected):
    assert startup.win_path(value) == expected


def test_older_bundled_pip_bootstraps_from_project_cwd_with_visible_errors(startup, tmp_path, monkeypatch):
    commands = []
    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[1:3] == ["-m", "venv"]:
            assert command[-1] == "--without-pip"
            Path(command[3]).mkdir(parents=True)
        if command[1:3] == ["-m", "ensurepip"]:
            assert kwargs["cwd"] == tmp_path
            assert kwargs["stdout"].name.endswith("setup.log")
            kwargs["stdout"].write("Original ensurepip error: simulated installer failure\n")
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(startup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Package setup failed"):
        startup.stage_environment(tmp_path, tmp_path / "missing-python")
    assert len(commands) == 2, "Do not continue to package installation after ensurepip fails"
    assert "Original ensurepip error" in (tmp_path / ".frib/setup.log").read_text()
    assert not (tmp_path / ".frib/active-environment.json").exists()
