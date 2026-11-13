"""A duplicate launch may reopen only this project's healthy running instance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from frib_ds import launcher


class HealthResponse:
    def __init__(self, payload=None, status=200, raw=None):
        self.status = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self.raw


@pytest.fixture
def running_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "PROJECT", tmp_path)
    monkeypatch.delenv("FRIB_DATA_DIR", raising=False)
    args = SimpleNamespace(api_port=8000, port=8501, local_ai=False, no_browser=False)
    receipt = {
        "schema_version": "1.0", "project": str(tmp_path), "api_port": 8000,
        "port": 8501, "data_dir": str((tmp_path / "data-local-ai").resolve()),
        "local_ai": False, "instance_id": "a" * 32,
    }
    receipt_path = tmp_path / ".frib/running-services.json"
    receipt_path.parent.mkdir()
    visits = []
    health = {
        "http://127.0.0.1:8000/health": HealthResponse({"status": "ok", "instance_id": "a" * 32}),
        "http://127.0.0.1:8501/_stcore/health": HealthResponse(raw=b"ok"),
    }

    def urlopen(url, **kwargs):
        visits.append(url)
        assert url in health, f"Unexpected service or external URL: {url}"
        response = health[url]
        if isinstance(response, Exception):
            raise response
        return response

    def write_receipt():
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    write_receipt()
    monkeypatch.setattr(launcher, "urlopen", urlopen)
    startup = SimpleNamespace(guard_control_path=lambda path: Path(path))
    return SimpleNamespace(
        args=args, startup=startup, receipt=receipt, receipt_path=receipt_path,
        visits=visits, health=health, write_receipt=write_receipt, project=tmp_path,
    )


def test_matching_project_instance_is_authenticated_before_reopening(running_instance):
    instance = running_instance
    assert launcher.running_app_url(instance.startup, instance.args) == "http://127.0.0.1:8501"
    assert instance.visits == [
        "http://127.0.0.1:8000/health", "http://127.0.0.1:8501/_stcore/health",
    ]


@pytest.mark.parametrize("arguments,expected", [
    ([], (8000, 8501, False, False)),
    (["--api-port", "8010"], (8010, 8501, True, False)),
    (["--port=8510"], (8000, 8510, False, True)),
    (["--api-port=8010", "--port", "8510"], (8010, 8510, True, True)),
])
def test_argument_parser_preserves_explicit_port_intent(arguments, expected):
    args = launcher.parse_launcher_args(arguments)
    assert (args.api_port, args.port, args.api_port_explicit, args.port_explicit) == expected


@pytest.mark.parametrize("arguments", [
    ["--port=80"], ["--api-port", "65536"], ["--port=8000"], ["--api-p", "8010"],
])
def test_argument_parser_rejects_invalid_or_ambiguous_ports(arguments):
    with pytest.raises(SystemExit) as failure:
        launcher.parse_launcher_args(arguments)
    assert failure.value.code == 2


def test_unspecified_ports_reopen_the_same_workspaces_authenticated_saved_ports(running_instance):
    instance = running_instance
    instance.args.api_port_explicit = instance.args.port_explicit = False
    instance.receipt.update(api_port=18000, port=18501)
    instance.write_receipt()
    instance.health["http://127.0.0.1:18000/health"] = HealthResponse({"status": "ok", "instance_id": "a" * 32})
    instance.health["http://127.0.0.1:18501/_stcore/health"] = HealthResponse(raw=b"ok")
    assert launcher.running_app_url(instance.startup, instance.args) == "http://127.0.0.1:18501"
    assert instance.visits == ["http://127.0.0.1:18000/health", "http://127.0.0.1:18501/_stcore/health"]


def test_unspecified_ports_still_refuse_a_receipt_with_one_shared_service_port(running_instance):
    instance = running_instance
    instance.args.api_port_explicit = instance.args.port_explicit = False
    instance.receipt.update(api_port=18000, port=18000)
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


@pytest.mark.parametrize("explicit", ["api_port", "port"])
def test_explicit_port_mismatch_never_reopens_saved_automatic_ports(running_instance, explicit):
    instance = running_instance
    instance.args.api_port_explicit = instance.args.port_explicit = False
    setattr(instance.args, explicit + "_explicit", True)
    instance.receipt.update(api_port=18000, port=18501)
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2.0"),
    ("project", "/unrelated/project"),
    ("data_dir", "/unrelated/demo-data"),
    ("local_ai", True),
    ("api_port", 8001),
    ("port", 8502),
    ("instance_id", "not-a-uuid"),
    ("instance_id", "g" * 32),
])
def test_mismatched_receipt_is_refused_before_contacting_services(running_instance, field, value):
    instance = running_instance
    instance.receipt[field] = value
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


@pytest.mark.parametrize("api_port,port", [(80, 8501), (8000, 65536), (8501, 8501)])
def test_invalid_port_pair_is_refused_even_when_receipt_matches(running_instance, api_port, port):
    instance = running_instance
    instance.args.api_port, instance.args.port = api_port, port
    instance.receipt.update(api_port=api_port, port=port)
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


def test_different_demo_data_workspace_cannot_reopen_existing_instance(running_instance, monkeypatch):
    instance = running_instance
    monkeypatch.setenv("FRIB_DATA_DIR", str(instance.project / "demo_session_data"))
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


def test_matching_custom_data_workspace_can_reopen_existing_instance(running_instance, monkeypatch):
    instance = running_instance
    custom = instance.project / "demo_session_data"
    monkeypatch.setenv("FRIB_DATA_DIR", str(custom))
    instance.receipt["data_dir"] = str(custom.resolve())
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) == "http://127.0.0.1:8501"


def test_local_ai_mode_requires_its_separate_matching_workspace(running_instance):
    instance = running_instance
    instance.args.local_ai = True
    instance.receipt.update(local_ai=True, data_dir=str((instance.project / "data-local-ai").resolve()))
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) == "http://127.0.0.1:8501"


@pytest.mark.parametrize("content", [None, "invalid json", "null", "[]"])
def test_missing_or_corrupt_receipt_does_not_contact_services(running_instance, content):
    instance = running_instance
    if content is None:
        instance.receipt_path.unlink()
    else:
        instance.receipt_path.write_text(content, encoding="utf-8")
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


def test_redirected_control_path_is_refused(running_instance):
    instance = running_instance

    def refused(path):
        raise RuntimeError("A redirected control path is not permitted")

    instance.startup.guard_control_path = refused
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == []


@pytest.mark.parametrize("response", [
    HealthResponse({"status": "ok", "instance_id": "b" * 32}),
    HealthResponse({"status": "ok"}),
    HealthResponse({"status": "starting", "instance_id": "a" * 32}),
    HealthResponse({"status": "ok", "instance_id": "a" * 32}, status=503),
    HealthResponse(raw=b"not json"),
    OSError("Backend unavailable"),
])
def test_unhealthy_or_unrelated_backend_never_authenticates_dashboard(running_instance, response):
    instance = running_instance
    instance.health["http://127.0.0.1:8000/health"] = response
    assert launcher.running_app_url(instance.startup, instance.args) is None
    assert instance.visits == ["http://127.0.0.1:8000/health"]


@pytest.mark.parametrize("response", [HealthResponse(raw=b"starting", status=503), OSError("Dashboard offline")])
def test_backend_alone_is_not_enough_to_reopen_dashboard(running_instance, response):
    instance = running_instance
    instance.health["http://127.0.0.1:8501/_stcore/health"] = response
    assert launcher.running_app_url(instance.startup, instance.args) is None


def test_receipt_cannot_supply_external_urls(running_instance):
    instance = running_instance
    instance.receipt.update(
        api_url="https://unrelated.invalid/health",
        dashboard_url="https://unrelated.invalid/dashboard",
        url="file:///unrelated/application",
    )
    instance.write_receipt()
    assert launcher.running_app_url(instance.startup, instance.args) == "http://127.0.0.1:8501"
    assert instance.visits == [
        "http://127.0.0.1:8000/health", "http://127.0.0.1:8501/_stcore/health",
    ]


def denied_lock_startup(instance, monkeypatch):
    class DeniedLock:
        def __init__(self, path):
            self.path = path

        def acquire(self):
            return False

        def close(self):
            pytest.fail("Duplicate launch does not own the running instance's lock")

    instance.startup.ProjectLock = DeniedLock
    instance.startup.check_environment = lambda *args: {"ok": True}
    monkeypatch.setattr(launcher, "startup_module", lambda: instance.startup)
    monkeypatch.setattr(launcher, "available_port", lambda *args: pytest.fail("Reopening does not reserve service ports"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Duplicate launch must not start services"))
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: pytest.fail("Duplicate launch must not start services"))


@pytest.mark.parametrize("held", [False, True])
def test_healthy_reopen_precedes_dependency_repair_and_service_lock(running_instance, monkeypatch, held):
    instance = running_instance
    plan = instance.project / ".frib/pending-upgrade.json"
    plan.write_bytes(b"reviewed update remains queued")
    actions = []

    class ExistingServiceLock:
        def __init__(self, path):
            actions.append("lock constructed")

        def acquire(self):
            actions.append("lock acquired")
            return not held

    instance.startup.ProjectLock = ExistingServiceLock
    instance.startup.check_environment = lambda *args: pytest.fail("Reopen must precede repair or upgrade checks")
    monkeypatch.setattr(launcher, "startup_module", lambda: instance.startup)
    monkeypatch.setattr(launcher, "available_port", lambda *args: pytest.fail("Do not select ports for a healthy workspace"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Do not replace healthy services"))
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args: pytest.fail("--no-browser must be honored"))
    assert launcher.main(["--no-browser"]) == 0
    assert actions == []
    assert plan.read_bytes() == b"reviewed update remains queued"


@pytest.mark.parametrize("no_browser", [False, True])
def test_duplicate_launch_returns_success_without_starting_or_stopping_services(running_instance, monkeypatch, capsys, no_browser):
    instance = running_instance
    denied_lock_startup(instance, monkeypatch)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(launcher.sys, "argv", ["frib-start", *(["--no-browser"] if no_browser else [])])
    assert launcher.main() == 0
    assert opened == ([] if no_browser else ["http://127.0.0.1:8501"])
    output = capsys.readouterr().out.casefold()
    assert "already open" in output and "http://127.0.0.1:8501" in output
    assert "original launcher" in output


def test_busy_lock_without_authenticated_app_does_not_open_browser_or_start_services(running_instance, monkeypatch, capsys):
    instance = running_instance
    instance.receipt_path.unlink()
    denied_lock_startup(instance, monkeypatch)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args: pytest.fail("Do not reopen an unauthenticated app"))
    monkeypatch.setattr(launcher.sys, "argv", ["frib-start"])
    assert launcher.main() == 1
    assert instance.visits == []
    output = capsys.readouterr().out.casefold()
    assert "ctrl+c" in output and "not started another copy" in output


def test_native_reopen_ready_event_cannot_claim_ownership_of_running_workspace(running_instance, monkeypatch):
    instance = running_instance
    denied_lock_startup(instance, monkeypatch)
    events = []
    instance.startup.startup_progress = lambda *args, **kwargs: events.append((args, kwargs))
    monkeypatch.setenv("FRIB_STARTUP_WINDOW", "1")
    assert launcher.main(["--no-browser"]) == 0
    assert events[0][0][0] == "ready"
    assert events[0][1] == {"url": "http://127.0.0.1:8501", "owned": False}


@pytest.mark.skipif(os.name != "posix", reason="POSIX socket reuse semantics")
def test_available_port_refuses_a_live_reusable_listener():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert launcher.available_port(port) is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX socket reuse semantics")
def test_available_port_accepts_an_immediately_closed_connected_listener():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.socket() as client:
            client.connect(("127.0.0.1", port))
            connection, _ = listener.accept()
            # The server actively closes; receiving EOF ensures its FIN reached
            # the client before the client completes the connection shutdown.
            connection.close()
            assert client.recv(1) == b""
    assert launcher.available_port(port) is True
