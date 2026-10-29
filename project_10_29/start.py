"""Private, transactional setup and startup; requires only Python's stdlib."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import uuid


PROJECT = Path(__file__).resolve().parent
IMPORTS = {"pydantic": "pydantic", "pydantic-settings": "pydantic_settings", "pyyaml": "yaml",
    "numpy": "numpy", "pandas": "pandas", "scipy": "scipy", "fastapi": "fastapi",
    "uvicorn": "uvicorn", "requests": "requests", "python-multipart": "multipart",
    "pypdf": "pypdf", "streamlit": "streamlit", "plotly": "plotly", "httpx": "httpx"}
OPTIONAL_IMPORTS = {"sentence-transformers": "sentence_transformers", "chromadb": "chromadb", "torch": "torch", "pytest": "pytest"}


def win_path(path):
    """Let child Python/pip handle deep paths without changing Windows policy."""
    value = os.fspath(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + str(Path(value).absolute())


def guard_control_path(path):
    """Reject links/junctions before accessing any managed setup location."""
    path = Path(path).absolute()
    root = next((parent for parent in (path, *path.parents) if parent.name == ".frib"), None)
    if root is None:
        raise RuntimeError("Setup path is outside the project's private runtime folder.")
    current = root
    for part in (None, *path.relative_to(root).parts):
        if part is not None:
            current /= part
        try: info = current.lstat()
        except FileNotFoundError: continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or (current.is_file() and info.st_nlink > 1):
            raise RuntimeError("Refusing a redirected private runtime path: " + str(current))
    return path


class ProjectLock:
    """An OS lock, released after crashes; contains no application evidence."""
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def acquire(self):
        guard_control_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError("Refusing a redirected startup lock.")
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if not self.stream.tell():
            self.stream.write(b"\0"); self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close(); self.stream = None
            return False
        return True

    def close(self):
        if self.stream is None:
            return
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close(); self.stream = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another FRIB setup is already running. Wait for its window to finish, then retry.")
        return self

    def __exit__(self, *_):
        self.close()


def atomic_json(path, payload):
    path = guard_control_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, allow_nan=False)
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def environment_python(directory):
    return Path(directory) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def active_python(project):
    root = Path(project).resolve() / ".frib"
    pointer = guard_control_path(root / "active-environment.json")
    if not pointer.exists():
        return environment_python(Path(project) / ".venv")
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("The private environment pointer is invalid; it must contain one JSON object.")
    relative = payload.get("path", "")
    if payload.get("schema_version") != "1.0" or not isinstance(relative, str) or not re.fullmatch(r"environments/ENV-[a-f0-9]{32}", relative):
        raise RuntimeError("The private environment pointer is invalid. Restore its previous validated value before starting.")
    directory = guard_control_path(root / relative)
    if directory.resolve().parent != (root / "environments").resolve():
        raise RuntimeError("The private environment points outside its managed directory.")
    return environment_python(directory)


# Executed inside the candidate interpreter. No package is changed by this probe.
PROBE = r'''
import importlib, importlib.metadata, json, pathlib, struct, sys, tomllib
issues=[]
versions={}
project=pathlib.Path(sys.argv[1]).resolve()
test_lab=sys.argv[2]=='1'
mapping=json.loads(sys.argv[3])
optional=json.loads(sys.argv[4])
python_version='.'.join(map(str,sys.version_info[:3]))
try:
    from packaging.requirements import Requirement
except Exception as exc:
    print(json.dumps({'ok':False,'issues':['packaging version checker unavailable: '+str(exc)],'python_version':python_version})); raise SystemExit(0)
configuration=tomllib.loads((project/'pyproject.toml').read_text(encoding='utf-8'))
requirements=configuration['project']['dependencies']+configuration['project']['optional-dependencies']['ui']
if test_lab: requirements += ['httpx>=0.27']
if sys.version_info < (3,11) or struct.calcsize('P') != 8:
    issues.append('Python 3.11 or newer, 64-bit, is required')
for text in requirements:
    requirement=Requirement(text)
    name=requirement.name.lower().replace('_','-')
    try:
        version=importlib.metadata.version(requirement.name)
        versions[name]=version
        if version not in requirement.specifier: issues.append(name+' '+version+' does not satisfy '+str(requirement.specifier))
        importlib.import_module(mapping[name])
    except Exception as exc:
        issues.append(name+': '+type(exc).__name__+': '+str(exc))
for name in ['ssl','venv','pip','packaging','watchfiles','websockets','httptools','dotenv']:
    try: importlib.import_module(name)
    except Exception as exc: issues.append(name+': '+type(exc).__name__+': '+str(exc))
for distribution,module in optional.items():
    try: importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError: continue
    try: importlib.import_module(module)
    except Exception as exc: issues.append(distribution+' optional package: '+type(exc).__name__+': '+str(exc))
try:
    import frib_ds
    if not pathlib.Path(frib_ds.__file__).resolve().is_relative_to(project/'src'):
        issues.append('Application package points at another project copy')
except Exception as exc: issues.append('frib_ds: '+str(exc))
print(json.dumps({'ok':not issues,'issues':issues,'versions':versions,'python_version':'.'.join(map(str,sys.version_info[:3]))}))
'''


def check_environment(python, project, test_lab=False):
    if not Path(python).is_file():
        return {"ok": False, "issues": ["Private application environment is missing"]}
    try:
        checked = subprocess.run([win_path(python), "-c", PROBE, str(project), "1" if test_lab else "0", json.dumps(IMPORTS), json.dumps(OPTIONAL_IMPORTS)],
            cwd=project, capture_output=True, text=True, timeout=60)
        if checked.returncode:
            return {"ok": False, "issues": [(checked.stderr or checked.stdout or "Python environment probe failed").strip()[-2000:]]}
        result = json.loads(checked.stdout.strip().splitlines()[-1])
        if result["ok"]:
            consistent = subprocess.run([win_path(python), "-m", "pip", "check"], cwd=project,
                capture_output=True, text=True, timeout=60)
            if consistent.returncode:
                result["ok"] = False
                result["issues"].append("Dependency compatibility: " + (consistent.stdout or consistent.stderr).strip()[-2000:])
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "issues": [type(exc).__name__ + ": " + str(exc)]}


def plan_tools(project):
    source = Path(project) / "src/frib_ds/system_manager.py"
    spec = importlib.util.spec_from_file_location("frib_setup_system_manager", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("The upgrade validator is missing from this project copy.")
    module = importlib.util.module_from_spec(spec)
    # Dataclass/type annotation helpers expect their defining module to exist.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pending_upgrade(project):
    path = guard_control_path(Path(project) / ".frib/pending-upgrade.json")
    if not path.exists():
        return None, None
    raw = path.read_bytes()
    if len(raw) > 100_000:
        raise RuntimeError("The queued upgrade plan exceeds its safe size limit.")
    try:
        payload = json.loads(raw)
        tools = plan_tools(project)
        plan = tools.validate_upgrade_plan(payload)
        if plan.get("include_semantic") or plan.get("upgrade_python"):
            request = {key: plan[key] for key in ("mode", "components", "upgrade_pip", "upgrade_python", "include_semantic")}
            tools.build_upgrade_plan(request, tools.inspect_hardware(project))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("The queued upgrade plan is invalid: " + str(exc)) from exc
    return plan, raw


def ensure_stopped(project, arguments):
    lock = ProjectLock(Path(project) / ".frib/services.lock")
    if not lock.acquire():
        raise RuntimeError("Stop FRIB with Ctrl+C in its running window, then double-click Start FRIB.cmd to apply setup or upgrades.")
    # Older launchers did not write a service lock. Never guess process identity
    # or terminate another program: occupied requested ports require a stop.
    ports = {"--api-port": 8000, "--port": 8501}
    for key in ports:
        if key in arguments:
            index = arguments.index(key)
            try: ports[key] = int(arguments[index + 1])
            except (IndexError, ValueError):
                lock.close()
                raise RuntimeError("Supply a valid port number after " + key)
    if any(not 1024 <= port <= 65535 for port in ports.values()) or len(set(ports.values())) != 2:
        lock.close()
        raise RuntimeError("Choose two different ports between 1024 and 65535.")
    for port in ports.values():
        with socket.socket() as connection:
            try: connection.bind(("127.0.0.1", port))
            except OSError:
                lock.close()
                raise RuntimeError(f"Port {port} is in use. Stop the previous FRIB services (Ctrl+C) before changing their environment, or choose unused ports.") from None
    return lock


def freeze_requirements(python, project):
    completed = subprocess.run([win_path(python), "-m", "pip", "freeze", "--all"],
        cwd=project, capture_output=True, text=True, timeout=60)
    if completed.returncode:
        # importlib.metadata is in the stdlib and still works if pip itself is
        # missing. Do not lose optional packages just to repair the installer.
        snapshot = subprocess.run([win_path(python), "-c", "import importlib.metadata as m,json; print(json.dumps([{'name':d.metadata['Name'],'version':d.version,'direct':d.read_text('direct_url.json')} for d in m.distributions()]))"],
            cwd=project, capture_output=True, text=True, timeout=60)
        if snapshot.returncode:
            raise RuntimeError("The current runtime cannot report its installed packages. Its environment was retained; restore the runtime before retrying.")
        entries = json.loads(snapshot.stdout)
        for entry in entries:
            if entry.get("direct") and entry["name"].lower().replace("_", "-") != "frib-decision-support":
                raise RuntimeError("An external URL package prevents automatic cloning. The working environment was retained.")
        completed.stdout = "\n".join(entry["name"] + "==" + entry["version"] for entry in entries)
    lines = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e "):
            if Path(line[3:]).resolve() == Path(project).resolve():
                continue
            raise RuntimeError("An external editable package prevents automatic environment cloning. The working environment was retained.")
        if any(line.lower().startswith(name + "==") for name in ("frib-decision-support", "pip", "setuptools", "wheel")):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+!-]*", line):
            raise RuntimeError("An external URL or non-pinned package prevents automatic cloning. The working environment was retained.")
        lines.append(line)
    return lines


def stage_environment(project, current, plan=None, test_lab=False, current_version=None):
    root = Path(project) / ".frib"
    directory = guard_control_path(root / "environments" / ("ENV-" + uuid.uuid4().hex))
    directory.parent.mkdir(parents=True, exist_ok=True)
    if Path(current).is_file() and current_version is None:
        version_probe = subprocess.run([win_path(current), "-c", "import sys; print('.'.join(map(str,sys.version_info[:3])))"],
            cwd=project, capture_output=True, text=True, timeout=10)
        reported = version_probe.stdout.strip()
        if version_probe.returncode or not re.fullmatch(r"3\.(?:11|12|13)\.\d+", reported):
            raise RuntimeError("The active Python runtime could not be verified. It was retained; restore that runtime before retrying setup.")
        current_version = reported
    base = str(current) if Path(current).is_file() else getattr(sys, "_base_executable", sys.executable)
    target_minor = tuple(map(int, current_version.split(".")[:2])) if current_version else sys.version_info[:2]
    if plan and plan.get("upgrade_python"):
        base = str(root / "python" / plan["python_runtime"] / "python.exe")
        if os.name != "nt" or not Path(base).is_file():
            raise RuntimeError("The queued Python runtime is not ready. Run Start FRIB.cmd to prepare the verified Windows runtime first.")
        target_minor = (3, 13)
    receipt = {"schema_version": "1.0", "status": "staging", "plan_id": plan.get("plan_id") if plan else None,
        "previous_python": str(current), "staged_path": directory.relative_to(root).as_posix(),
        "started_at": datetime.now(timezone.utc).isoformat(), "log_path": str(root / "setup.log")}
    atomic_json(root / "last-upgrade.json", receipt)
    log_path = guard_control_path(root / "setup.log")
    try:
        print("Preparing a replacement application environment...", flush=True)
        with log_path.open("a", encoding="utf-8") as log:
            def run(command):
                completed = subprocess.run(command, cwd=project, stdout=log, stderr=subprocess.STDOUT)
                if completed.returncode:
                    raise RuntimeError(f"Package setup failed (exit {completed.returncode}). Details: {log_path}")
            # Older bundled pip versions reject an extended venv working
            # directory ending in '\\.'. Venv runs ensurepip from that folder;
            # bootstrap it explicitly from our ordinary project cwd instead.
            # This also sends the full ensurepip diagnostic to setup.log.
            run([win_path(base), "-m", "venv", win_path(directory), "--without-pip"])
            python = environment_python(directory)
            run([win_path(python), "-m", "ensurepip", "--upgrade", "--default-pip"])
            if Path(current).is_file():
                frozen = freeze_requirements(current, project)
                selected_names = set(plan.get("components", [])) if plan else set()
                frozen = [line for line in frozen if line.split("==", 1)[0].lower().replace("_", "-") not in selected_names]
                source_minor = tuple(map(int, current_version.split(".")[:2])) if current_version else target_minor
                if source_minor != target_minor:
                    # Old binary wheel pins may not support a newer Python.
                    # Keep each installed capability while resolving versions
                    # for the new runtime, then validate the complete result.
                    frozen = [line.split("==", 1)[0] for line in frozen]
                    receipt["cross_python_resolution"] = True
                    receipt["warning"] = "Installed package names were preserved; compatible versions were resolved for the new Python runtime instead of forcing incompatible old binary pins."
                    print(receipt["warning"], flush=True)
                if frozen:
                    frozen_path = directory / "previous-packages.txt"
                    frozen_path.write_text("\n".join(frozen) + "\n", encoding="utf-8")
                    print("Copying installed package versions into the replacement...", flush=True)
                    run([win_path(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(frozen_path)])
            if plan and plan.get("upgrade_pip"):
                run([win_path(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])
            if plan:
                selected = plan_tools(project).build_install_requirements(plan)
                if selected:
                    print("Applying the reviewed upgrade selection in the replacement...", flush=True)
                    run([win_path(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", *selected])
            print("Installing required application packages (internet is needed for missing downloads)...", flush=True)
            run([win_path(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(project) + "[ui]"])
            if test_lab:
                run([win_path(python), "-m", "pip", "install", "--disable-pip-version-check", "httpx>=0.27"])
        result = check_environment(python, project, test_lab)
        if not result["ok"]:
            raise RuntimeError("Replacement validation failed: " + "; ".join(result["issues"]))
        if plan and plan.get("upgrade_python") and result.get("python_version") != plan["python_runtime"]:
            raise RuntimeError("Replacement Python version does not match the requested verified runtime " + plan["python_runtime"])
        receipt.update(status="validated", validated_at=datetime.now(timezone.utc).isoformat(), versions=result.get("versions", {}))
        atomic_json(root / "last-upgrade.json", receipt)
        return python, result, receipt
    except Exception as exc:
        receipt.update(status="failed", error=str(exc), previous_environment_retained=True)
        atomic_json(root / "last-upgrade.json", receipt)
        raise RuntimeError(str(exc) + " The previous environment and project data were retained; retry after correcting the connection or dependency conflict.") from exc


def prepare_environment(project, arguments):
    project = Path(project).resolve()
    test_lab = "--test-lab" in arguments
    with ProjectLock(project / ".frib/setup.lock"):
        current = active_python(project)
        plan, raw_plan = pending_upgrade(project)
        checked = check_environment(current, project, test_lab)
        if checked["ok"] and plan is None:
            return current
        service_guard = ensure_stopped(project, arguments)
        try:
            if plan:
                print("Applying the upgrade queued for this launch...", flush=True)
            else:
                print("Required setup checks: " + "; ".join(checked["issues"]), flush=True)
            try:
                python, validated, receipt = stage_environment(project, current, plan, test_lab, checked.get("python_version"))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                if plan is None or not checked["ok"]:
                    raise
                print("Queued upgrade failed: " + str(exc), flush=True)
                print("The validated previous environment is still active. Starting it so you can retry or cancel the retained plan in System & upgrades > Startup plan. The failure receipt and pending plan were retained.", flush=True)
                return current
            relative = python.parent.parent.relative_to(project / ".frib").as_posix()
            atomic_json(project / ".frib/active-environment.json", {"schema_version": "1.0", "path": relative,
                "python_version": validated.get("python_version"), "validated_at": receipt["validated_at"], "plan_id": receipt["plan_id"]})
            receipt.update(status="applied", applied_at=datetime.now(timezone.utc).isoformat())
            atomic_json(project / ".frib/last-upgrade.json", receipt)
            pending = project / ".frib/pending-upgrade.json"
            if raw_plan is not None and pending.exists() and pending.read_bytes() == raw_plan:
                pending.unlink()
            print("Application environment validated and ready.", flush=True)
            return python
        finally:
            service_guard.close()


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if sys.version_info < (3, 11):
        print("FRIB requires Python 3.11 or newer. On Windows, use Start FRIB.cmd for automatic private runtime setup.")
        return 1
    python = prepare_environment(PROJECT, arguments)
    if arguments == ["--check"]:
        print(f"FRIB installation is ready. Project: {PROJECT}")
        return 0
    if "--test-lab" in arguments:
        arguments.remove("--test-lab")
        if "--output" not in arguments:
            arguments += ["--output", str(PROJECT / "test_lab_results")]
        command = [win_path(python), win_path(PROJECT / "scripts/run_test_lab.py"), *arguments]
    else:
        command = [win_path(python), "-m", "frib_ds.launcher", *arguments]
    process = subprocess.Popen(command, cwd=PROJECT)
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            return process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate(); process.wait(timeout=10)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Setup could not continue: " + str(exc), flush=True)
        raise SystemExit(1)
