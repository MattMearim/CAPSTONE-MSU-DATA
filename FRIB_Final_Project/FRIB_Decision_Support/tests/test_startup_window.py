"""Native startup stays optional and owns only the processes it launches."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import queue
import errno
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def window():
    spec = importlib.util.spec_from_file_location("isolated_startup_window", PROJECT / "startup_window.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event_line(**details):
    return "FRIB_STARTUP_EVENT=" + json.dumps(details)


@pytest.mark.parametrize("stage", ["application", "ai", "workspace"])
def test_known_progress_stages_are_parsed(window, stage):
    event = {"stage": stage, "message": "A real completed check or current task"}
    assert window.parse_event(event_line(**event)) == event


@pytest.mark.parametrize("url", ["http://127.0.0.1:8501", "http://127.0.0.1:18501/"])
def test_ready_requires_a_loopback_workspace_and_explicit_ownership(window, url):
    event = {"stage": "ready", "message": "Workspace ready", "url": url, "owned": False}
    assert window.parse_event(event_line(**event)) == event


@pytest.mark.parametrize("url", [
    "https://example.org", "file:///etc/passwd", "http://localhost:8501",
    "http://127.0.0.1:80", "http://user@127.0.0.1:8501", "http://127.0.0.1:8501/other",
    "http://127.0.0.1:8501/?redirect=other", "http://127.0.0.1:8501/#other", "http://127.0.0.1:99999",
])
def test_logs_cannot_supply_an_external_or_arbitrary_ready_link(window, url):
    assert window.parse_event(event_line(stage="ready", message="Ready", url=url, owned=True)) is None


@pytest.mark.parametrize("line", [
    "FRIB is ready: https://untrusted.invalid", "FRIB_STARTUP_EVENT=[]", "FRIB_STARTUP_EVENT=not json",
    event_line(stage="unknown", message="Unknown"), event_line(stage="ai", message=123),
    event_line(stage="ai", message="x" * 1001),
    event_line(stage="ready", message="Ready", url="http://127.0.0.1:8501"),
    event_line(stage="ready", message="Ready", url="http://127.0.0.1:8501", owned="true"),
])
def test_untrusted_or_malformed_output_is_only_a_log(window, line):
    assert window.parse_event(line) is None


def read_exit(session):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        generation, kind, value = session.events.get(timeout=4)
        if kind == "exit":
            return generation, value
    pytest.fail("Owned startup child did not exit")


@pytest.mark.skipif(os.name != "posix", reason="POSIX owned process group shutdown")
def test_retry_waits_for_owned_child_shutdown_and_exit_acknowledgement(window, tmp_path):
    (tmp_path / "start.py").write_text(
        "import signal, time\nsignal.signal(signal.SIGTERM, lambda *args: exit(0))\n"
        "print('child ready', flush=True)\nwhile True: time.sleep(.05)\n", encoding="utf-8")
    session = window.StartupSession([], tmp_path)
    try:
        assert session.start()
        generation, kind, value = session.events.get(timeout=5)
        assert (kind, value) == ("line", "child ready")
        original = session.process
        assert not session.start()
        assert session.process is original
        assert session.stop()
        assert not session.stop()
        finished_generation, code = read_exit(session)
        assert code == 0
        # Reader completion, not a button click, authorizes another child.
        assert not session.start()
        assert not session.completed(finished_generation - 1)
        assert session.running
        assert session.completed(finished_generation)
        assert session.start()
        assert session.process is not original
        session.events.get(timeout=5)
        assert session.stop()
        finished_generation, code = read_exit(session)
        assert session.completed(finished_generation)
        assert not session.running
    finally:
        session.stop()
        if session.shutdown_thread is not None:
            session.shutdown_thread.join(timeout=5)


def test_idle_window_never_signals_an_existing_service(window, monkeypatch):
    monkeypatch.setattr(window.os, "killpg", lambda *args: pytest.fail("No owned process group exists"), raising=False)
    session = window.StartupSession([])
    assert session.stop() is False


def test_reopened_workspace_window_cannot_stop_the_original(window):
    view = object.__new__(window.StartupWindow)
    view.session = SimpleNamespace(running=True, stop=lambda: pytest.fail("Reopened workspace is unowned"))
    view.owned = False
    closed = []
    view.close = lambda: closed.append(True)
    view.stop()
    assert closed == [True]


def test_completed_stages_do_not_regress_from_late_output(window):
    view = object.__new__(window.StartupWindow)
    view.stage_index = 2
    view.session = SimpleNamespace(stopping=False)
    view.apply_event({"stage": "ai", "message": "Late AI output"})
    assert view.stage_index == 2


def test_certificate_failure_keeps_verification_and_offers_actionable_retry(window):
    message = window.friendly_failure(["[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"])
    assert "secure download" in message and "Retry" in message and "details" in message
    assert "disable" not in message.casefold()


def test_startup_events_are_opt_in_and_do_not_change_console_output(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("isolated_progress_source", PROJECT / "start.py")
    startup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(startup)
    monkeypatch.delenv("FRIB_STARTUP_WINDOW", raising=False)
    startup.startup_progress("ai", "Loading semantic search")
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("FRIB_STARTUP_WINDOW", "1")
    startup.startup_progress("ready", "Ready", url="http://127.0.0.1:8501", owned=True)
    assert json.loads(capsys.readouterr().out.split("=", 1)[1])["owned"] is True


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="Unix dispatch")
@pytest.mark.parametrize("arguments", [[], ["--check"], ["--test-lab"], ["--no-browser"], ["--setup-local-ai"]])
def test_noninteractive_launchers_keep_the_existing_console_dispatch(tmp_path, arguments):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(PROJECT / "scripts/start_unix.sh", scripts / "start_unix.sh")
    (tmp_path / "start.py").write_text("import sys,json; print(json.dumps(sys.argv[1:]))", encoding="utf-8")
    (tmp_path / "startup_window.py").write_text("raise RuntimeError('Headless launches must not open Tk')", encoding="utf-8")
    result = subprocess.run(["bash", str(scripts / "start_unix.sh"), *arguments],
        env={**os.environ, "FRIB_PYTHON": sys.executable}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == arguments


@pytest.mark.skipif(os.name != "posix" or shutil.which("bash") is None, reason="Interactive Unix dispatch")
@pytest.mark.parametrize("arguments,override,expected", [
    (["--local-ai"], {}, "window"),
    (["--local-ai", "--no-browser"], {}, "console"),
    (["--local-ai", "--check"], {}, "console"),
    (["--test-lab"], {}, "console"),
    (["--local-ai"], {"FRIB_NO_GUI": "1"}, "console"),
    (["--local-ai"], {"SSH_CONNECTION": "test remote session"}, "console"),
])
def test_interactive_finder_start_selects_window_only_for_normal_local_use(tmp_path, arguments, override, expected):
    import pty
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(PROJECT / "scripts/start_unix.sh", scripts / "start_unix.sh")
    for filename, mode in (("start.py", "console"), ("startup_window.py", "window")):
        (tmp_path / filename).write_text("import json,sys; print(json.dumps([" + repr(mode) + ",sys.argv[1:]]))", encoding="utf-8")
    environment = {**os.environ, "FRIB_PYTHON": sys.executable}
    for name in ("FRIB_NO_GUI", "SSH_CONNECTION", "SSH_TTY"):
        environment.pop(name, None)
    environment.update(override)
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(["bash", str(scripts / "start_unix.sh"), *arguments],
            env=environment, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        slave = None
        chunks = []
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
        assert process.wait(timeout=10) == 0
        assert json.loads(b"".join(chunks).decode().splitlines()[-1]) == [expected, arguments]
    finally:
        os.close(master)
        if slave is not None:
            os.close(slave)


def test_missing_tk_falls_back_without_starting_a_second_child(window, monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    calls = []
    monkeypatch.setattr(window.subprocess, "call", lambda command, **kwargs: calls.append(command) or 7)
    assert window.main(["--local-ai"]) == 7
    assert calls == [[sys.executable, str(PROJECT / "start.py"), "--local-ai"]]


def test_display_failure_falls_back_to_console(window, monkeypatch):
    class NoDisplay(Exception):
        pass
    fake = SimpleNamespace(TclError=NoDisplay, ttk=object(), messagebox=object())
    def no_root():
        raise NoDisplay("no display")
    fake.Tk = no_root
    monkeypatch.setitem(sys.modules, "tkinter", fake)
    calls = []
    monkeypatch.setattr(window.subprocess, "call", lambda command, **kwargs: calls.append(command) or 0)
    assert window.main(["--local-ai"]) == 0
    assert len(calls) == 1
