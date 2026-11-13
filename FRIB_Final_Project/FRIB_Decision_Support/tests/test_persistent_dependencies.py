"""Installed packages survive extraction without sharing application source."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIB_AI_HOME", str(tmp_path / "permanent FRIB"))
    monkeypatch.setenv("FRIB_PERSISTENT_PYTHON", "1")
    startup = load(PROJECT / "start.py", "shared_test_start")
    tools = load(PROJECT / "scripts/persistent_dependencies.py", "shared_test_dependencies")
    return startup, tools


def project_copy(path, label):
    (path / "src/frib_ds").mkdir(parents=True)
    (path / "src/frib_ds/__init__.py").write_text("identity = " + repr(label) + "\n")
    shutil.copyfile(PROJECT / "src/frib_ds/ai_storage.py", path / "src/frib_ds/ai_storage.py")
    (path / "pyproject.toml").write_text('''[project]
name = "frib-decision-support"
version = "0.4.0"
requires-python = ">=3.11"
dependencies = ["demo-dependency>=1"]
[project.optional-dependencies]
ui = []
''')
    return path


def source_environment(project, startup):
    directory = project / ".frib/environments" / ("ENV-" + "a" * 32)
    subprocess.run([sys.executable, "-m", "venv", str(directory), "--without-pip"], check=True)
    python = startup.environment_python(directory)
    site = Path(subprocess.check_output([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    (site / "demo_dependency.py").write_text("value = 'installed once'\n")
    metadata = site / "demo_dependency-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: demo-dependency\nVersion: 1.0\n")
    app = site / "frib_decision_support-0.4.0.dist-info"
    app.mkdir()
    (app / "METADATA").write_text("Metadata-Version: 2.1\nName: frib-decision-support\nVersion: 0.4.0\n")
    (site / "__editable__.frib_decision_support-0.4.0.pth").write_text(str(project / "src") + "\n")
    return python


def validating_api(startup):
    def check(python, project, *_args):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        script = "import demo_dependency,frib_ds,importlib.metadata as m,json; print(json.dumps({'source':frib_ds.__file__,'identity':frib_ds.identity,'dependency':demo_dependency.value,'version':m.version('frib-decision-support')}))"
        checked = subprocess.run([str(python), "-c", script], cwd=project, env=env,
                                 capture_output=True, text=True, timeout=30)
        if checked.returncode:
            return {"ok": False, "issues": [checked.stderr]}
        result = json.loads(checked.stdout)
        assert Path(result["source"]).is_relative_to(Path(project) / "src")
        assert result["dependency"] == "installed once" and result["version"] == "0.4.0"
        return {"ok": True, "issues": [], "versions": {"demo-dependency": "1.0"}, "identity": result["identity"]}
    return SimpleNamespace(guard_control_path=startup.guard_control_path, environment_python=startup.environment_python,
                           atomic_json=startup.atomic_json, check_environment=check)


def test_new_extract_reuses_packages_without_old_source_or_any_pip_download(shared, tmp_path):
    startup, tools = shared
    old = project_copy(tmp_path / "old extract", "old")
    source = source_environment(old, startup)
    api = validating_api(startup)
    receipt = tools.publish(old, source, api)
    snapshot = Path(receipt["shared_dependencies"])
    assert (snapshot / "site-packages/demo_dependency.py").is_file()
    assert not list((snapshot / "site-packages").glob("*frib*"))
    assert not list((snapshot / "site-packages").glob("__editable__*"))
    # Removing the complete old extract proves no source/venv pointer is reused.
    shutil.rmtree(old)
    new = project_copy(tmp_path / "new extract", "new")
    reused, checked, result = tools.reuse(new, api)
    assert checked["identity"] == "new"
    assert str(new / "src") == result["source_overlay"]
    assert reused.is_file()
    assert not (reused.parent.parent / "bin/pip").exists(), "Reuse creates no installer and never calls pip"
    assert Path(result["shared_dependencies"]) == snapshot


def test_changed_requirements_and_other_interpreter_manifest_are_not_reused(shared, tmp_path):
    startup, tools = shared
    project = project_copy(tmp_path / "extract", "source")
    source = source_environment(project, startup)
    snapshot = Path(tools.publish(project, source, validating_api(startup))["shared_dependencies"])
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["base_python"] = "/tmp/untrusted-interpreter"
    manifest_path.write_text(json.dumps(manifest))
    assert tools.snapshots(project) == []
    manifest["runtime"] = tools.runtime_key()
    manifest_path.write_text(json.dumps(manifest))
    (project / "pyproject.toml").write_text((project / "pyproject.toml").read_text().replace("demo-dependency>=1", "demo-dependency>=2"))
    assert tools.snapshots(project) == []


def test_linked_dependency_is_rejected_before_shared_cache_activation(shared, tmp_path):
    startup, tools = shared
    project = project_copy(tmp_path / "extract", "source")
    source = source_environment(project, startup)
    site = next((source.parent.parent / "lib").glob("python*/site-packages"))
    secret = tmp_path / "outside.txt"
    secret.write_text("do not publish")
    (site / "linked.txt").symlink_to(secret)
    with pytest.raises(RuntimeError, match="redirected dependency"):
        tools.publish(project, source, validating_api(startup))
    assert tools.snapshots(project) == []
    assert not (project / ".frib/shared-python.json").exists()


def test_queued_upgrade_never_reuses_cache_instead_of_applying_plan(shared, tmp_path, monkeypatch):
    startup, _tools = shared
    monkeypatch.setattr(startup, "check_environment", lambda *_args: {"ok": False, "issues": ["missing"]})
    monkeypatch.setattr(startup, "pending_upgrade", lambda *_args: ({"plan_id": "reviewed"}, None))
    monkeypatch.setattr(startup, "ensure_stopped", lambda *_args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(startup, "reuse_shared_dependencies", lambda *_args: pytest.fail("A queued plan must stage its reviewed upgrades"))
    def stage(*_args):
        raise RuntimeError("planned upgrade attempted")
    monkeypatch.setattr(startup, "stage_environment", stage)
    with pytest.raises(RuntimeError, match="planned upgrade attempted"):
        startup.prepare_environment(tmp_path, ["--api-port", "54941", "--port", "54942"])
