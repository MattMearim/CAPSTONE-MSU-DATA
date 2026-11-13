"""Adversarial packaging, fixture paths and managed-process shutdown regressions.

Every payload and process is disposable. No test connects to a running FRIB
service or reads an actual credential, upload or operational record.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import zipfile
from urllib.error import HTTPError
from urllib.request import Request
from email.message import Message

import pytest

from frib_ds import launcher
from frib_ds import system_manager
from frib_ds.config import Config
from frib_ds.dashboard.test_lab_ui import bundle_examples, lab_file


PROJECT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, PROJECT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def startup():
    return load_module("security_startup", "start.py")


@pytest.mark.parametrize("relative", [
    "docs/.env", "src/.env.production", "config/secrets.toml",
    "docs/credentials.json", "docs/private.pem", "src/private.key",
    "docs/.git/config", "sample_data/.DS_Store", "docs/saved.sqlite3",
])
def test_source_distribution_excludes_nested_private_files(relative):
    package = load_module("security_source_package", "scripts/package_project.py")
    assert package.included(Path(relative)) is False


def test_source_distribution_keeps_deliberate_public_environment_examples():
    package = load_module("security_source_package", "scripts/package_project.py")
    assert package.included(Path(".env.example")) is True
    assert package.included(Path(".env.demo")) is True
    assert package.included(Path(".streamlit/config.toml")) is True


def test_external_source_link_aborts_before_creating_archive(tmp_path, monkeypatch):
    package = load_module("security_source_package", "scripts/package_project.py")
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / ".streamlit").mkdir()
    (project / ".streamlit/config.toml").write_text("[server]\n", encoding="utf-8")
    disposable_secret = tmp_path / "private.txt"
    disposable_secret.write_text("SYNTHETIC-SECRET-NEVER-PUBLISH", encoding="utf-8")
    (project / "docs/leaked.txt").symlink_to(disposable_secret)
    output = tmp_path / "portable.zip"
    monkeypatch.setattr(package, "PROJECT", project)
    monkeypatch.setattr(sys, "argv", ["package_project.py", str(output)])
    with pytest.raises(ValueError, match="redirected"):
        package.main()
    assert not output.exists()
    assert disposable_secret.read_text(encoding="utf-8") == "SYNTHETIC-SECRET-NEVER-PUBLISH"


def test_source_distribution_refuses_a_hardlinked_private_file(tmp_path, monkeypatch):
    package = load_module("security_source_package", "scripts/package_project.py")
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    private = tmp_path / "private.txt"
    private.write_text("SYNTHETIC-SECRET", encoding="utf-8")
    linked = project / "docs/linked.txt"
    os.link(private, linked)
    monkeypatch.setattr(package, "PROJECT", project)
    with pytest.raises(ValueError, match="unlinked"):
        package.checked_source(linked)


@pytest.fixture
def lab_project(tmp_path):
    project = tmp_path / "project"
    fixture = project / "sample_data/test_lab/demo.csv"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("time,value\n0,1\n", encoding="utf-8")
    return project


@pytest.mark.parametrize("relative", [
    "sample_data/test_lab/../test_lab/demo.csv",
    "sample_data/test_lab/./demo.csv",
    "sample_data//test_lab/demo.csv",
    "sample_data\\test_lab\\demo.csv",
    "sample_data/test_lab/demo.csv:private",
    "/sample_data/test_lab/demo.csv",
])
def test_download_zip_refuses_noncanonical_or_cross_platform_paths(lab_project, relative):
    manifest = {"datasets": [{"path": relative}], "procedures": []}
    with pytest.raises(ValueError):
        bundle_examples(lab_project, manifest)


def test_fixture_root_symlink_cannot_redirect_test_lab_outside_project(tmp_path, lab_project):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("SYNTHETIC-SECRET", encoding="utf-8")
    (lab_project / "sample_docs").mkdir()
    (lab_project / "sample_docs/test_lab").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        lab_file(lab_project, "sample_docs/test_lab/private.txt")


def test_test_lab_download_preserves_safe_files_and_member_names(lab_project):
    relative = "sample_data/test_lab/demo.csv"
    manifest = {"datasets": [{"path": relative}], "procedures": []}
    with zipfile.ZipFile(io.BytesIO(bundle_examples(lab_project, manifest))) as archive:
        assert archive.read(relative) == b"time,value\n0,1\n"
        assert all(".." not in Path(name).parts for name in archive.namelist())


@pytest.mark.parametrize("member", [
    "Live_Demo_Data/import_options/../../outside.json",
    "/outside.txt", "C:/outside.txt", "docs\\outside.txt", "docs/file:stream",
])
def test_final_bundle_rejects_traversal_and_windows_stream_members(member):
    package = load_module("security_final_package", "scripts/package_final_bundle.py")
    with pytest.raises(ValueError, match="plain relative path"):
        package.archive_member(member)


@pytest.mark.parametrize("name", ["../private", "/private", "nested/scenario", "..\\private", "x:stream", ""])
def test_scenario_config_rejects_path_components_before_reading(tmp_path, name):
    configuration = Config.__new__(Config)
    configuration.config_dir = tmp_path
    with pytest.raises(ValueError, match="plain identifiers"):
        configuration.scenario(name)


def test_scenario_config_refuses_a_redirected_scenarios_folder(tmp_path):
    configuration = Config.__new__(Config)
    configuration.config_dir = tmp_path / "config"
    configuration.config_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "demo.yaml").write_text("private: SYNTHETIC\n", encoding="utf-8")
    (configuration.config_dir / "scenarios").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside"):
        configuration.scenario("demo")


@pytest.mark.parametrize("xml", [
    b'<!DOCTYPE testsuites [<!ENTITY repeated "expanded">]><testsuites><testcase name="&repeated;"/></testsuites>',
    b'<!DOCTYPE testsuites SYSTEM "file:///DO-NOT-READ"><testsuites/>',
    '<!DOCTYPE testsuites [<!ENTITY x "expanded">]><testsuites/>'.encode("utf-16"),
    b"<testsuites>" + b" " * 8_000_000 + b"</testsuites>",
])
def test_showcase_refuses_entity_xml_alternative_encoding_and_oversized_reports(tmp_path, xml):
    showcase = load_module("security_showcase", "scripts/build_l1_l2_showcase.py")
    report = tmp_path / "untrusted.xml"
    report.write_bytes(xml)
    result = showcase.load_junit(report, tmp_path / "showcase.html")
    assert result["available"] is False
    assert result["warning"] and result["tests"] == []


def test_environment_probe_rejects_a_vulnerable_bundled_installer(startup):
    override = '''
import importlib.metadata
original_version = importlib.metadata.version
def installed_version(name):
    return "23.2.1" if name == "pip" else original_version(name)
importlib.metadata.version = installed_version
'''
    checked = subprocess.run([sys.executable, "-c", override + startup.PROBE,
                              str(PROJECT), "0", json.dumps(startup.IMPORTS), json.dumps(startup.OPTIONAL_IMPORTS)],
                             cwd=PROJECT, capture_output=True, text=True, timeout=30)
    assert checked.returncode == 0, checked.stderr
    result = json.loads(checked.stdout.strip().splitlines()[-1])
    assert result["ok"] is False
    assert any("pip 23.2.1" in issue and "security minimum" in issue for issue in result["issues"])


def test_candidate_updates_bundled_pip_before_installing_project_packages(startup, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(startup.subprocess, "run", lambda command, **kwargs: commands.append(command) or type("Result", (), {"returncode": 0})())
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True, "versions": {}, "python_version": "3.12.10"})
    startup.stage_environment(tmp_path, tmp_path / "missing-python")
    ensurepip = next(index for index, command in enumerate(commands) if command[1:3] == ["-m", "ensurepip"])
    secured = next(index for index, command in enumerate(commands) if "pip>=26.1.2" in command)
    project_install = next(index for index, command in enumerate(commands) if "-e" in command)
    assert ensurepip < secured < project_install


@pytest.mark.parametrize("url", [
    "file:///tmp/private", "https://unrelated.invalid/health", "http://localhost:8000/health",
    "http://127.0.0.1:8000/private", "http://127.0.0.1:8000/health?url=private",
    "http://user@127.0.0.1:8000/health", "http://127.0.0.1:80/health",
])
def test_service_health_opener_refuses_nonlocal_schemes_hosts_and_endpoints(monkeypatch, url):
    monkeypatch.setattr(launcher._HEALTH_OPENER, "open", lambda *args, **kwargs: pytest.fail("Unsafe health URL must be rejected before opening"))
    with pytest.raises(ValueError, match="loopback"):
        launcher.urlopen(url)


@pytest.mark.parametrize("url", [
    "https://unrelated.invalid/pypi/pip/json", "http://pypi.org/pypi/pip/json",
    "https://pypi.org/pypi/unknown-package/json", "https://pypi.org/pypi/pip/json?x=1",
    "https://user@pypi.org/pypi/pip/json",
])
def test_metadata_opener_refuses_unofficial_or_unlisted_endpoints(monkeypatch, url):
    monkeypatch.setattr(system_manager._METADATA_OPENER, "open", lambda *args, **kwargs: pytest.fail("Unsafe metadata URL must be rejected before opening"))
    with pytest.raises(ValueError, match="allowlisted"):
        system_manager.urlopen(Request(url))


@pytest.mark.parametrize("handler,url", [
    (launcher._NoHealthRedirects, "http://127.0.0.1:8000/health"),
    (system_manager._NoMetadataRedirects, "https://pypi.org/pypi/pip/json"),
])
def test_health_and_metadata_redirects_are_refused_before_second_request(handler, url):
    headers = Message()
    headers["Location"] = "https://unrelated.invalid/private"
    with pytest.raises(HTTPError):
        handler().http_error_302(Request(url), io.BytesIO(b""), 302, "Found", headers)


@pytest.mark.skipif(os.name != "posix", reason="POSIX termination and terminal-close signals")
@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGHUP])
def test_terminal_close_and_termination_run_cleanup_and_restore_handlers(tmp_path, termination):
    # Use a real disposable child to ensure these are OS signals, not merely
    # mocked function calls. The child never starts a server or touches data.
    marker = tmp_path / "cleaned.json"
    code = r'''
import importlib.util, json, os, pathlib, signal, sys
spec = importlib.util.spec_from_file_location("shutdown_test", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
previous = signal.getsignal(signal.SIGTERM)
handlers = module.ShutdownSignals(); handlers.install()
print("READY", flush=True)
try:
    while True: signal.pause()
except KeyboardInterrupt:
    handlers.ignore_during_cleanup()
    # Repeated interruption during cleanup must be harmless.
    os.kill(os.getpid(), signal.SIGINT)
    os.kill(os.getpid(), signal.SIGTERM)
finally:
    handlers.close()
    pathlib.Path(sys.argv[2]).write_text(json.dumps({"cleaned": True, "restored": signal.getsignal(signal.SIGTERM) == previous}))
'''
    process = subprocess.Popen([sys.executable, "-u", "-c", code, str(PROJECT / "start.py"), str(marker)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        process.send_signal(termination)
        _, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        assert json.loads(marker.read_text(encoding="utf-8")) == {"cleaned": True, "restored": True}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_outer_launcher_forwards_shutdown_and_waits_for_its_owned_child(startup, monkeypatch):
    calls = []

    class Child:
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if timeout is None:
                raise KeyboardInterrupt
            return 0

        def poll(self):
            return None

        def terminate(self):
            calls.append(("terminate",))

    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(startup, "prepare_environment", lambda *args: Path(sys.executable))
    monkeypatch.setattr(startup.subprocess, "Popen", lambda *args, **kwargs: Child())
    assert startup.main(["--no-browser"]) == 0
    assert calls == [("wait", None), ("terminate",), ("wait", 20)]
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize("needs_setup", [False, True])
def test_managed_launcher_shutdown_cleans_every_owned_service_and_releases_lock(startup, tmp_path, monkeypatch, needs_setup):
    from frib_ds import local_ai
    from types import SimpleNamespace
    monkeypatch.setattr(local_ai, "ensure_ollama", lambda *args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(local_ai, "check_ollama_model", lambda *args: {"model_available": True})
    monkeypatch.setattr(local_ai, "setup_needed", lambda *args: needs_setup)
    calls = []
    monkeypatch.setattr(local_ai, "main", lambda arguments: calls.append(("ai-setup", arguments)) or 0)

    class Lock:
        def __init__(self, path):
            pass

        def acquire(self):
            return True

        def close(self):
            calls.append("unlock")

    class Service:
        def __init__(self, number):
            self.number = number

        def poll(self):
            return None

        def terminate(self):
            calls.append(("terminate", self.number))

        def wait(self, timeout=None):
            calls.append(("wait", self.number))
            return 0

    def child(*args, **kwargs):
        calls.append(("start", sum(isinstance(item, tuple) and item[0] == "start" for item in calls)))
        return Service(calls[-1][1])

    def stop(_delay):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(launcher, "PROJECT", tmp_path)
    monkeypatch.delenv("FRIB_DATA_DIR", raising=False)
    monkeypatch.setattr(startup, "ProjectLock", Lock)
    monkeypatch.setattr(startup, "check_environment", lambda *args: {"ok": True})
    monkeypatch.setattr(launcher, "startup_module", lambda: startup)
    monkeypatch.setattr(launcher, "available_port", lambda _port: True)
    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher.time, "sleep", stop)
    previous = signal.getsignal(signal.SIGTERM)
    previous_environment = {key: os.environ.get(key) for key in ("FRIB_CONFIG_DIR", "FRIB_DATA_DIR", "HF_HOME", "FRIB_EMBEDDING_CACHE")}
    assert launcher.main(["--no-browser"]) == 0
    assert (("ai-setup", ["--install"]) in calls) is needs_setup
    assert {key: os.environ.get(key) for key in previous_environment} == previous_environment
    assert ("terminate", 0) in calls and ("terminate", 1) in calls
    assert ("wait", 0) in calls and ("wait", 1) in calls
    assert calls[-1] == "unlock"
    assert not (tmp_path / ".frib/running-services.json").exists()
    assert signal.getsignal(signal.SIGTERM) == previous
