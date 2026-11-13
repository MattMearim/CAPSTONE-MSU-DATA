"""Reuse installed Python dependencies across extracted FRIB copies, offline.

Only third-party packages are shared. Each project gets a small local Python
environment whose source path and application metadata refer to that project.
The module intentionally uses only the Python standard library.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tomllib
import uuid


def storage_tools(project):
    path = Path(project) / "src/frib_ds/ai_storage.py"
    spec = importlib.util.spec_from_file_location("frib_python_shared_storage", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The shared storage helper is missing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enabled():
    return os.environ.get("FRIB_PERSISTENT_PYTHON", "1") != "0" and (
        sys.platform == "darwin" or bool(os.environ.get("FRIB_AI_HOME")))


def runtime_key():
    # Never execute a base interpreter supplied by a cache manifest. Only this
    # launcher's already-running, known base Python may create a local overlay.
    return {"base_python": str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
            "cache_tag": sys.implementation.cache_tag,
            "soabi": sysconfig.get_config_var("SOABI"),
            "platform": sysconfig.get_platform(), "machine": platform.machine()}


def project_requirements(project):
    configuration = tomllib.loads((Path(project) / "pyproject.toml").read_text(encoding="utf-8"))
    package = configuration["project"]
    requirements = package["dependencies"] + package["optional-dependencies"]["ui"]
    return configuration, requirements


def requirements_key(project):
    configuration, requirements = project_requirements(project)
    payload = {"requirements": sorted(requirements), "runtime": runtime_key(),
               "python": configuration["project"].get("requires-python"), "schema_version": "1.0"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def cache_root(project):
    storage = storage_tools(project)
    return storage.guard_path(storage.ai_home() / "python"), storage


def snapshots(project):
    root, storage = cache_root(project)
    directory = storage.guard_path(root / "environments")
    if not directory.exists():
        return []
    key = requirements_key(project)
    matches = []
    for path in directory.iterdir():
        if not path.name.startswith("ENV-"):
            continue
        storage.guard_path(path)
        manifest_path = storage.guard_path(path / "manifest.json")
        if not manifest_path.is_file() or manifest_path.stat().st_size > 1_000_000:
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if (isinstance(manifest, dict) and manifest.get("schema_version") == "1.0"
                and manifest.get("requirements_key") == key and manifest.get("runtime") == runtime_key()
                and manifest.get("status") == "validated"):
            site = storage.guard_path(path / "site-packages")
            if site.is_dir():
                matches.append((path, manifest))
    return sorted(matches, key=lambda item: item[1].get("created_at", ""), reverse=True)


SOURCE_PROBE = r'''
import importlib.metadata as metadata, json, pathlib, sys, sysconfig
application_files=[]
versions={}
external_editables=[]
libraries=list(dict.fromkeys([sysconfig.get_path('purelib'),sysconfig.get_path('platlib')]))
for distribution in metadata.distributions():
    name=distribution.metadata.get('Name','').lower().replace('_','-')
    if not name: continue
    if name=='frib-decision-support':
        for entry in distribution.files or []:
            application_files.append(str(pathlib.Path(distribution.locate_file(entry)).resolve()))
        continue
    direct=distribution.read_text('direct_url.json')
    if direct:
        try:
            if json.loads(direct).get('dir_info',{}).get('editable'):
                external_editables.append(name)
        except (ValueError,AttributeError):
            external_editables.append(name)
    versions[name]=distribution.version
print(json.dumps({'libraries':libraries,'versions':versions,'application_files':application_files,
    'external_editables':external_editables,'base_python':str(pathlib.Path(getattr(sys,'_base_executable',sys.executable)).resolve())}))
'''


def describe_source(python, project):
    probe = subprocess.run([str(python), "-c", SOURCE_PROBE], cwd=project,
                           capture_output=True, text=True, timeout=60)
    if probe.returncode:
        raise RuntimeError("Cannot inspect the installed Python packages: " + probe.stderr.strip()[-1000:])
    payload = json.loads(probe.stdout.strip().splitlines()[-1])
    if payload.get("external_editables"):
        raise RuntimeError("Unrelated editable packages cannot be shared across project copies.")
    if payload.get("base_python") != runtime_key()["base_python"]:
        raise RuntimeError("The installed environment uses a different base Python; retain it locally.")
    return payload


def copy_dependencies(source, destination, excluded, storage):
    """Copy ordinary installed files; never copy links or source-path hooks."""
    source = Path(source)
    for entry in source.iterdir():
        if entry.name in {"__pycache__", "frib_ds"}:
            continue
        normalized = entry.name.lower().replace("-", "_")
        if (entry.resolve() in excluded or normalized.startswith("frib_decision_support")
                or normalized.startswith("__editable__") or entry.suffix == ".egg-link"):
            continue
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RuntimeError("Cannot share a redirected dependency: " + entry.name)
        target = storage.guard_path(destination / entry.name)
        if stat.S_ISDIR(info.st_mode):
            storage.ensure_directory(target)
            copy_dependencies(entry, target, excluded, storage)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            if entry.suffix == ".pth":
                # Ordinary package hooks (e.g. setuptools) are retained, while
                # absolute/relative source path entries cannot leak old copies.
                text = entry.read_text(encoding="utf-8")
                if any(line.strip() and not line.lstrip().startswith(("#", "import ", "import\t"))
                       for line in text.splitlines()):
                    continue
            if target.exists():
                if target.read_bytes() != entry.read_bytes():
                    raise RuntimeError("Conflicting installed dependency files: " + entry.name)
                continue
            shutil.copy2(entry, target, follow_symlinks=False)
        else:
            raise RuntimeError("Cannot share a non-ordinary dependency file: " + entry.name)


def create_overlay(project, snapshot, startup, test_lab=False):
    project = Path(project).resolve()
    directory = startup.guard_control_path(project / ".frib/environments" / ("ENV-" + uuid.uuid4().hex))
    directory.parent.mkdir(parents=True, exist_ok=True)
    base = runtime_key()["base_python"]
    result = subprocess.run([base, "-m", "venv", str(directory), "--without-pip"],
                            cwd=project, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Cannot prepare a local Python source overlay: " + result.stderr.strip()[-1000:])
    python = startup.environment_python(directory)
    paths = subprocess.run([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                           cwd=project, capture_output=True, text=True, timeout=30)
    if paths.returncode:
        raise RuntimeError("Cannot locate the local Python package directory.")
    site = startup.guard_control_path(Path(paths.stdout.strip()))
    if not site.is_relative_to(directory) or not site.is_dir():
        raise RuntimeError("The local Python package directory is outside its environment.")
    configuration, requirements = project_requirements(project)
    source = project / "src"
    if any(character in str(source) + str(snapshot) for character in "\r\n"):
        raise RuntimeError("Python environment paths cannot contain line breaks.")
    # Source first; the shared snapshot never contains the application itself.
    (site / "frib-current-project.pth").write_text(str(source) + "\n", encoding="utf-8")
    shared = Path(snapshot) / "site-packages"
    (site / "frib-shared-dependencies.pth").write_text(
        "import site; site.addsitedir(" + repr(str(shared)) + ")\n", encoding="utf-8")
    version = configuration["project"]["version"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,99}", version):
        raise RuntimeError("The project package version is not a supported metadata value.")
    if any(not isinstance(item, str) or "\r" in item or "\n" in item for item in requirements):
        raise RuntimeError("Project dependency declarations cannot contain line breaks.")
    metadata = site / ("frib_decision_support-" + version + ".dist-info")
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: frib-decision-support\nVersion: " + version + "\n"
        + "".join("Requires-Dist: " + item + "\n" for item in requirements), encoding="utf-8")
    (metadata / "direct_url.json").write_text(json.dumps({"url": project.as_uri(), "dir_info": {"editable": True}}), encoding="utf-8")
    (metadata / "INSTALLER").write_text("frib-shared-dependencies\n", encoding="utf-8")
    validated = startup.check_environment(python, project, test_lab)
    if not validated["ok"]:
        shutil.rmtree(directory)
        raise RuntimeError("Shared Python dependency validation failed: " + "; ".join(validated["issues"]))
    receipt = {"schema_version": "1.0", "status": "validated", "plan_id": None,
               "validated_at": datetime.now(timezone.utc).isoformat(), "shared_dependencies": str(snapshot),
               "source_overlay": str(source), "versions": validated.get("versions", {})}
    startup.atomic_json(directory / "shared-dependencies.json", receipt)
    return python, validated, receipt


def publish(project, python, startup):
    """Publish installed third-party packages once, without any downloads."""
    project = Path(project).resolve()
    overlay_receipt = Path(python).parent.parent / "shared-dependencies.json"
    if overlay_receipt.is_file():
        return json.loads(overlay_receipt.read_text(encoding="utf-8"))
    root, storage = cache_root(project)
    key = requirements_key(project)
    receipt_path = startup.guard_control_path(project / ".frib/shared-python.json")
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("source_python") == str(python) and receipt.get("requirements_key") == key:
            for path, _manifest in snapshots(project):
                if str(path) == receipt.get("shared_dependencies"):
                    return receipt
    with storage.AIStorageLock():
        source = describe_source(python, project)
        environment = Path(python).parent.parent.resolve()
        if any(not Path(library).resolve().is_relative_to(environment) for library in source["libraries"]):
            raise RuntimeError("Dependency libraries must belong to the validated source environment.")
        for path, manifest in snapshots(project):
            if manifest.get("dependency_versions") == source["versions"]:
                receipt = {"schema_version": "1.0", "source_python": str(python),
                           "requirements_key": key, "shared_dependencies": str(path)}
                startup.atomic_json(receipt_path, receipt)
                return receipt
        directory = storage.ensure_directory(root / "environments" / ("ENV-" + uuid.uuid4().hex))
        destination = storage.ensure_directory(directory / "site-packages")
        probe_overlay = None
        try:
            print("Saving installed Python dependencies on this Mac for future project extracts (no downloads)...", flush=True)
            excluded = {Path(value) for value in source["application_files"]}
            for library in source["libraries"]:
                copy_dependencies(library, destination, excluded, storage)
            probe_overlay, _checked, _receipt = create_overlay(project, directory, startup)
            manifest = {"schema_version": "1.0", "status": "validated", "requirements_key": key,
                        "runtime": runtime_key(), "dependency_versions": source["versions"],
                        "created_at": datetime.now(timezone.utc).isoformat()}
            storage.atomic_json(directory / "manifest.json", manifest)
            receipt = {"schema_version": "1.0", "source_python": str(python),
                       "requirements_key": key, "shared_dependencies": str(directory)}
            startup.atomic_json(receipt_path, receipt)
            return receipt
        except BaseException:
            shutil.rmtree(directory)
            raise
        finally:
            if probe_overlay is not None:
                shutil.rmtree(probe_overlay.parent.parent)


def reuse(project, startup, test_lab=False):
    """Select a fully checked snapshot, keeping any installed environment intact."""
    for path, _manifest in snapshots(project):
        try:
            return create_overlay(project, path, startup, test_lab)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print("A shared Python dependency snapshot was not usable: " + str(exc), flush=True)
    return None
