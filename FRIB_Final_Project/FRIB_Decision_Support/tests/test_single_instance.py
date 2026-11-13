"""Newest launch wins without stopping an unverified process or touching data."""
import importlib.util
import json
import os
from pathlib import Path
import signal

import pytest


@pytest.fixture
def control():
    source = Path(__file__).resolve().parents[1] / "scripts/single_instance.py"
    spec = importlib.util.spec_from_file_location("isolated_single_instance", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(project, pid=None, start="first", *, group=True):
    pid = os.getpid() if pid is None else pid
    return {"pid": pid, "start": start, "command": f"/usr/bin/python3.12 -u {project}/start.py --local-ai",
            "ppid": 10, "pgid": pid if group else 10}


def coordinator(control, project, state, **kwargs):
    own = identity(project)
    return control.SingleInstance(project, state_dir=state, probe=kwargs.pop("probe", lambda pid: own if pid == os.getpid() else None),
                                  discover=kwargs.pop("discover", lambda: []), **kwargs)


def test_registers_during_setup_without_requiring_api_and_releases_only_metadata(control, tmp_path):
    project, state = tmp_path / "project", tmp_path / "control"
    project.mkdir()
    evidence = project / "evidence.txt"
    evidence.write_bytes(b"preserved input")
    with coordinator(control, project, state) as app:
        owner = json.loads((state / "owner.json").read_text())
        assert owner["project"] == str(project) and owner["token"] == app.token
        assert owner["identity"]["pid"] == os.getpid()
        assert not control._Lock(state / "workspace.lock").acquire()
    assert not (state / "owner.json").exists()
    assert (state / "workspace.lock").exists(), "Never unlink an OS lock file"
    available = control._Lock(state / "workspace.lock")
    assert available.acquire()
    available.close()
    assert evidence.read_bytes() == b"preserved input"


def test_newer_request_gracefully_replaces_registered_startup_before_api_exists(control, tmp_path):
    state = tmp_path / "control"
    old = coordinator(control, tmp_path / "old", state)
    old.__enter__()
    stopped = []
    def handoff(owner):
        stopped.append(owner["token"])
        old.close()
    newer = coordinator(control, tmp_path / "new", state, terminate=handoff)
    with newer:
        assert stopped == [old.token]
        assert json.loads((state / "owner.json").read_text())["token"] == newer.token


def test_old_cleanup_cannot_delete_new_owners_receipt(control, tmp_path):
    state = tmp_path / "control"
    old = coordinator(control, tmp_path / "old", state)
    old.__enter__()
    newer = {"schema_version": "1.0", "token": "new-owner", "identity": identity(tmp_path / "new")}
    control._write(state / "owner.json", newer)
    old.close()
    assert json.loads((state / "owner.json").read_text()) == newer


def test_superseded_waiter_never_stops_newer_owner(control, tmp_path):
    state = tmp_path / "control"
    old = coordinator(control, tmp_path / "old", state)
    old.__enter__()
    stopped = []
    def another_request_wins():
        control._write(state / "request.json", {"token": "latest-request"})
        control._write(state / "owner.json", {"token": "latest-request", "project": str(tmp_path / "newer"),
                                                  "identity": identity(tmp_path / "newer")})
        return 0
    waiting = coordinator(control, tmp_path / "waiting", state, clock=another_request_wins,
                          terminate=lambda owner: stopped.append(owner))
    try:
        with pytest.raises(control.SupersededLaunch):
            waiting.__enter__()
        assert stopped == []
        assert json.loads((state / "owner.json").read_text())["token"] == "latest-request"
    finally:
        old.close()


def test_stale_owner_receipt_does_not_trigger_signal_when_os_lock_is_free(control, tmp_path):
    state = tmp_path / "control"
    state.mkdir()
    control._write(state / "owner.json", {"project": "old", "identity": identity("old", 99999)})
    with coordinator(control, tmp_path / "new", state, terminate=lambda _: pytest.fail("No process owns the stale receipt")):
        pass


@pytest.mark.parametrize("change", ["start", "command"])
def test_reused_pid_or_changed_command_is_never_signalled(control, tmp_path, monkeypatch, change):
    expected = identity(tmp_path, 4321)
    actual = dict(expected, **{change: "different"})
    monkeypatch.setattr(control.os, "kill", lambda *a: pytest.fail("Do not kill reused PID"))
    monkeypatch.setattr(control.os, "killpg", lambda *a: pytest.fail("Do not kill reused group"))
    with pytest.raises(RuntimeError, match="identity changed"):
        control.terminate_verified({"project": str(tmp_path), "identity": expected}, lambda _: actual)


def test_missing_process_is_not_signalled(control, tmp_path, monkeypatch):
    monkeypatch.setattr(control.os, "kill", lambda *a: pytest.fail("Stale PID is not running"))
    assert control.terminate_verified({"project": str(tmp_path), "identity": identity(tmp_path, 4321)}, lambda _: None) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX graceful shutdown")
@pytest.mark.parametrize("group", [False, True])
def test_only_verified_frib_identity_or_owned_group_receives_sigterm(control, tmp_path, monkeypatch, group):
    process = identity(tmp_path, 4321, group=group)
    signals = []
    monkeypatch.setattr(control.os, "kill", lambda *a: signals.append(("pid", *a)))
    monkeypatch.setattr(control.os, "killpg", lambda *a: signals.append(("group", *a)))
    assert control.terminate_verified({"project": str(tmp_path), "identity": process}, lambda _: process)
    assert signals == [("group" if group else "pid", 4321, signal.SIGTERM)]


def test_unrelated_program_never_receives_signal_even_with_matching_receipt(control, tmp_path, monkeypatch):
    process = identity(tmp_path, 4321)
    process["command"] = "/usr/bin/python3.12 unrelated.py"
    monkeypatch.setattr(control.os, "kill", lambda *a: pytest.fail("Unrelated program"))
    monkeypatch.setattr(control.os, "killpg", lambda *a: pytest.fail("Unrelated program"))
    with pytest.raises(RuntimeError, match="verified as FRIB"):
        control.terminate_verified({"project": str(tmp_path), "identity": process}, lambda _: process)


@pytest.mark.parametrize("command", [
    '/usr/bin/python3.12 -c "print(\'{project}/start.py\')"',
    '/usr/bin/python3.12 -c "print(\'-m frib_ds.launcher\')"',
    '/usr/bin/python3.12 unrelated.py {project}/start.py',
    '/usr/bin/python3.12 -m unrelated -m frib_ds.launcher',
])
def test_path_or_module_literals_do_not_authenticate_unrelated_python(control, tmp_path, command):
    command = command.format(project=tmp_path)
    assert not control._startup_command(command, tmp_path)
    assert not control._launcher_command(command)


def test_invalid_startup_cannot_supersede_a_valid_waiting_request(control, tmp_path):
    state = tmp_path / "control"
    state.mkdir()
    control._write(state / "request.json", {"token": "valid-current-startup"})
    process = identity(tmp_path / "new")
    process["command"] = "/usr/bin/python3.12 unrelated.py"
    bad = coordinator(control, tmp_path / "new", state, probe=lambda _: process)
    with pytest.raises(RuntimeError, match="verify this startup"):
        bad.__enter__()
    assert json.loads((state / "request.json").read_text())["token"] == "valid-current-startup"


def test_legacy_handoff_waits_for_old_startup_to_exit(control, tmp_path):
    old = identity(tmp_path / "legacy", 4321)
    stopped = []
    own = identity(tmp_path / "new")
    def probe(pid):
        return own if pid == os.getpid() else old if not stopped else None
    with coordinator(control, tmp_path / "new", tmp_path / "control", probe=probe,
                     discover=lambda: [{"project": str(tmp_path / "legacy"), "identity": old, "legacy": True}],
                     terminate=lambda owner: stopped.append(owner["identity"]["pid"])):
        assert stopped == [4321]


def test_handoff_timeout_never_force_kills_or_claims_ownership(control, tmp_path):
    state = tmp_path / "control"
    old = coordinator(control, tmp_path / "old", state)
    old.__enter__()
    elapsed = [0.0]
    signals = []
    newer = coordinator(control, tmp_path / "new", state, timeout=.2, clock=lambda: elapsed[0],
                        sleep=lambda delay: elapsed.__setitem__(0, elapsed[0] + delay),
                        terminate=lambda owner: signals.append(owner["token"]))
    try:
        with pytest.raises(RuntimeError, match="No process was force-stopped"):
            newer.__enter__()
        assert signals == [old.token]
        assert json.loads((state / "owner.json").read_text())["token"] == old.token
    finally:
        old.close()


class Health:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps(self.payload).encode()


@pytest.mark.parametrize("valid", [False, True])
def test_legacy_authentication_requires_both_fixed_loopback_health_checks(control, tmp_path, valid):
    (tmp_path / ".frib").mkdir()
    token = "a" * 32
    control._write(tmp_path / ".frib/running-services.json", {"pid": 4321, "project": str(tmp_path),
                                                            "api_port": 8000, "port": 8501, "instance_id": token})
    visits = []
    def open_health(url, **kwargs):
        visits.append(url)
        return Health({"status": "ok", "instance_id": token if valid else "b" * 32})
    assert control._healthy_legacy(tmp_path, 4321, open_health) is valid
    assert visits == (["http://127.0.0.1:8000/health", "http://127.0.0.1:8501/_stcore/health"] if valid
                      else ["http://127.0.0.1:8000/health"])


def test_legacy_receipt_cannot_authorize_an_unrelated_port_owner(control, tmp_path):
    (tmp_path / ".frib").mkdir()
    control._write(tmp_path / ".frib/running-services.json", {"pid": 9999, "project": str(tmp_path),
                                                            "api_port": 8000, "port": 8501, "instance_id": "a" * 32})
    assert not control._healthy_legacy(tmp_path, 4321, lambda *a, **kw: pytest.fail("Wrong PID cannot authorize health calls"))
