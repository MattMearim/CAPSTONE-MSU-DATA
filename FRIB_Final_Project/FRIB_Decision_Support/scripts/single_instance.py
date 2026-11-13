"""One FRIB workspace per user; the most recent launch owns the next start.

This stdlib-only coordinator is loaded before private dependencies exist. It
never searches for arbitrary port owners, force-kills a process, or removes OS
lock files. A handoff targets only a verified FRIB startup or launcher.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import uuid


class SupersededLaunch(RuntimeError):
    """A newer launch request has priority over this waiting startup."""


def default_state_dir():
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/FRIB"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "FRIB"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "FRIB"
    return base / "launch-control"


def _guard(path):
    path = Path(path).absolute()
    for current in (path, *path.parents):
        if current.is_symlink():
            raise RuntimeError("The FRIB launch-control folder cannot contain redirected paths.")
        if current.exists() and current.is_file() and current.stat().st_nlink != 1:
            raise RuntimeError("The FRIB launch-control file cannot be linked to another file.")
    return path


def _read(path):
    path = _guard(path)
    try:
        if path.stat().st_size > 32_768:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, ValueError, UnicodeError):
        return None


def _write(path, value):
    path = _guard(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class _Lock:
    def __init__(self, path):
        self.path, self.stream = _guard(path), None

    def acquire(self):
        stream = self.path.open("a+b")
        if not stream.seek(0, os.SEEK_END):
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def close(self):
        if self.stream is None:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
        self.stream = None


def _command_output(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ""


def process_identity(pid):
    """Return PID-reuse-resistant OS identity, or None once the process is gone."""
    if type(pid) is not int or pid <= 1:
        return None
    if os.name == "nt":
        script = ("$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid)
                  + "'; if($p){$p|Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine|ConvertTo-Json -Compress}")
        raw = _command_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
        if not raw:
            return None
        value = json.loads(raw)
        return {"pid": pid, "start": str(value.get("CreationDate")), "command": value.get("CommandLine") or "",
                "ppid": int(value.get("ParentProcessId") or 0), "pgid": None}
    stamp = _command_output(["ps", "-p", str(pid), "-o", "lstart="])
    command = _command_output(["ps", "-p", str(pid), "-o", "command="])
    if not stamp or not command:
        return None
    parent = _command_output(["ps", "-p", str(pid), "-o", "ppid="])
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return None
    return {"pid": pid, "start": stamp, "command": command, "ppid": int(parent or 0), "pgid": pgid}


def _python_rest(command):
    found = re.match(r'^(?:"([^"]+)"|(\S+))', command or "")
    first = (found.group(1) or found.group(2)) if found else ""
    if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", Path(first).name, re.I):
        return None
    rest = command[found.end():].lstrip()
    if rest == "-u" or rest.startswith("-u "):
        rest = rest[2:].lstrip()
    return rest


def _startup_command(command, project):
    script = str(Path(project).resolve() / "start.py")
    rest = _python_rest(command)
    if rest is None:
        return False
    for prefix in (script, '"' + script + '"'):
        if rest.startswith(prefix) and (len(rest) == len(prefix) or rest[len(prefix)].isspace()):
            return True
    return False


def _launcher_command(command):
    rest = _python_rest(command)
    return rest is not None and bool(re.match(r"-m\s+frib_ds\.launcher(?:\s|$)", rest))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Loopback health must not redirect", headers, fp)


_HTTP = build_opener(ProxyHandler({}), _NoRedirect())


def _healthy_legacy(project, pid, opener=None):
    """Authenticate old launchers through their existing project receipt."""
    opener = opener or _HTTP.open
    receipt = _read(Path(project) / ".frib/running-services.json")
    if not receipt or receipt.get("pid") != pid or receipt.get("project") != str(Path(project).resolve()):
        return False
    api, ui = receipt.get("api_port"), receipt.get("port")
    token = receipt.get("instance_id")
    if (any(type(port) is not int or not 1024 <= port <= 65535 for port in (api, ui)) or api == ui
            or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token)):
        return False
    try:
        with opener(f"http://127.0.0.1:{api}/health", timeout=2) as response:
            value = json.loads(response.read(65_536))
            if response.status != 200 or value.get("status") != "ok" or value.get("instance_id") != token:
                return False
        with opener(f"http://127.0.0.1:{ui}/_stcore/health", timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def legacy_instances(probe=process_identity):
    """Find only exact FRIB launchers, then prove their project and API identity."""
    if os.name == "nt":
        # CIM can authenticate registered owners; old Windows launchers lack a
        # safely addressable console group and require their own Stop control.
        return []
    candidates = []
    for line in _command_output(["ps", "-axo", "pid=,command="]).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or not _launcher_command(parts[1]):
            continue
        pid = int(parts[0])
        cwd = _command_output(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
        directory = next((row[1:] for row in cwd.splitlines() if row.startswith("n")), "")
        if not directory or not _healthy_legacy(directory, pid):
            continue
        identity = probe(pid)
        if identity is None or identity.get("command") != parts[1]:
            continue
        target = identity
        parent = probe(identity.get("ppid"))
        if parent and parent.get("pgid") == parent.get("pid") and _startup_command(parent.get("command", ""), directory):
            target = parent
        candidates.append({"project": str(Path(directory).resolve()), "identity": target, "legacy": True})
    return candidates


def terminate_verified(owner, probe=process_identity):
    identity = owner.get("identity") or {}
    pid = identity.get("pid")
    current = probe(pid)
    if current is None:
        return False
    if any(current.get(key) != identity.get(key) for key in ("pid", "start", "command")):
        raise RuntimeError("The earlier process identity changed. FRIB did not stop an unrelated application.")
    project = owner.get("project", "")
    if not (_startup_command(current.get("command", ""), project) or _launcher_command(current.get("command", ""))):
        raise RuntimeError("The earlier application could not be verified as FRIB. Stop it from its own window.")
    if os.name == "nt":
        if not owner.get("console_group"):
            raise RuntimeError("Stop the earlier FRIB startup window, then retry. Its Windows console group cannot be safely signalled.")
        os.kill(pid, signal.CTRL_BREAK_EVENT)
    elif current.get("pgid") == pid and identity.get("pgid") == pid:
        os.killpg(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    return True


class SingleInstance:
    def __init__(self, project, *, state_dir=None, timeout=45, probe=None, terminate=None,
                 discover=None, clock=None, sleep=None):
        self.project = Path(project).resolve()
        self.state_dir = _guard(state_dir or default_state_dir())
        self.timeout = timeout
        self.probe = probe or process_identity
        self.terminate = terminate or (lambda owner: terminate_verified(owner, self.probe))
        self.discover = discover or (lambda: legacy_instances(self.probe))
        self.clock, self.sleep = clock or time.monotonic, sleep or time.sleep
        self.token = uuid.uuid4().hex
        self.lock = None
        self.identity = None

    def _latest(self):
        request = _read(self.state_dir / "request.json")
        if not request or request.get("token") != self.token:
            raise SupersededLaunch("A newer FRIB launch has priority. This earlier startup was cancelled.")

    def _stop(self, owner):
        self._latest()
        if not owner or not isinstance(owner.get("identity"), dict):
            return
        # Recheck the request immediately before signalling a proven identity.
        self._latest()
        self.terminate(owner)

    def __enter__(self):
        self.identity = self.probe(os.getpid())
        if not self.identity or not _startup_command(self.identity.get("command", ""), self.project):
            raise RuntimeError("FRIB could not verify this startup process. Use the project's Start FRIB launcher.")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _write(self.state_dir / "request.json", {"schema_version": "1.0", "token": self.token,
                                                   "project": str(self.project), "pid": os.getpid()})
        self.lock = _Lock(self.state_dir / "workspace.lock")
        deadline = self.clock() + self.timeout
        signalled = set()
        try:
            while not self.lock.acquire():
                self._latest()
                owner = _read(self.state_dir / "owner.json")
                identity = (owner or {}).get("identity") or {}
                marker = (identity.get("pid"), identity.get("start"))
                if owner and marker not in signalled:
                    self._stop(owner)
                    signalled.add(marker)
                if self.clock() >= deadline:
                    raise RuntimeError("The earlier FRIB app is still shutting down. Wait for its startup window to close, then retry. No process was force-stopped.")
                self.sleep(.1)
            self._latest()
            # A legacy instance may predate this global lock. Wait for its
            # graceful shutdown before publishing the new owner or doing setup.
            for owner in self.discover():
                self._stop(owner)
                identity = owner["identity"]
                while True:
                    self._latest()
                    current = self.probe(identity["pid"])
                    if current is None or current.get("start") != identity.get("start"):
                        break
                    if self.clock() >= deadline:
                        raise RuntimeError("The earlier FRIB app did not finish shutting down. Stop it in its original startup window, then retry.")
                    self.sleep(.1)
            self._latest()
            _write(self.state_dir / "owner.json", {"schema_version": "1.0", "token": self.token,
                                                     "project": str(self.project), "identity": self.identity,
                                                     "console_group": os.name == "nt" and os.environ.get("FRIB_STARTUP_CONSOLE_GROUP") == "1"})
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lock is None or self.lock.stream is None:
            return
        owner = _read(self.state_dir / "owner.json")
        if owner and owner.get("token") == self.token and owner.get("identity") == self.identity:
            (self.state_dir / "owner.json").unlink(missing_ok=True)
        self.lock.close()

    def __exit__(self, *_):
        self.close()
