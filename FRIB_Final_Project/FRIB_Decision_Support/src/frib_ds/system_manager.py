"""Read-only host inventory and allowlisted upgrades queued for the next start.

Keep this module standard-library-only at import time: the first-run bootstrap
loads its plan validator before application dependencies are available. Nothing
here installs software, changes configuration, or accesses operational records.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

PROJECT = Path(__file__).resolve().parents[2]
TARGET_PYTHON = "3.13.16"
PYTHON_RELEASE_URL = "https://www.python.org/downloads/release/python-31316/"
PACKAGE_COMPONENTS = {
    "pydantic": ("Pydantic", "2.8", "core", "Validate event, signal and API data contracts."),
    "pydantic-settings": ("Pydantic Settings", "2.4", "core", "Typed application settings support."),
    "pyyaml": ("PyYAML", "6.0", "core", "Read local application and scenario configuration."),
    "numpy": ("NumPy", "2.0", "core", "Numerical arrays and waveform calculations."),
    "pandas": ("pandas", "2.2", "core", "Tabular evidence and CSV presentation."),
    "scipy": ("SciPy", "1.13", "core", "Scientific signal-processing functions."),
    "fastapi": ("FastAPI", "0.115", "core", "Serve the local application API."),
    "uvicorn": ("Uvicorn", "0.30", "core", "Run the local API server."),
    "requests": ("Requests", "2.32", "core", "Dashboard-to-API HTTP requests."),
    "python-multipart": ("python-multipart", "0.0.9", "core", "Receive uploaded evidence and procedures."),
    "pypdf": ("pypdf", "5.0", "core", "Extract selectable text from PDF evidence and procedures."),
    "streamlit": ("Streamlit", "1.64", "ui", "Interactive local engineering workbench."),
    "plotly": ("Plotly", "5.24", "ui", "Interactive plots with engineering units and source context."),
    "sentence-transformers": ("SentenceTransformers", "3.0", "ai", "Generate real semantic document embeddings with the configured local model."),
}
REQUIRED_IDS = tuple(PACKAGE_COMPONENTS)
SEMANTIC_REQUIREMENT = "sentence-transformers>=3.0"
_PLAN_KEYS = {"schema_version", "plan_id", "created_at", "apply_on", "status", "mode", "components",
              "upgrade_pip", "upgrade_python", "include_semantic", "requirements", "project_extras", "python_runtime",
              "hardware_summary", "rationale", "warnings"}


class _NoMetadataRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The official JSON endpoint is already canonical. A redirect is an
        # unavailable metadata check, never permission to contact another host.
        raise HTTPError(req.full_url, code, "Package metadata checks must not redirect.", headers, fp)


_METADATA_OPENER = build_opener(_NoMetadataRedirects())


def urlopen(request, timeout=3):
    """Network metadata is limited to canonical, allowlisted PyPI endpoints."""
    parsed = urlsplit(request.full_url)
    paths = {f"/pypi/{name}/json" for name in (*REQUIRED_IDS, "pip", "sentence-transformers")}
    if (parsed.scheme != "https" or parsed.netloc != "pypi.org" or parsed.path not in paths
            or parsed.query or parsed.fragment):
        raise ValueError("Package metadata must use an allowlisted official PyPI endpoint.")
    return _METADATA_OPENER.open(request, timeout=timeout)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _requirements(components, semantic):
    result = [("uvicorn[standard]" if item == "uvicorn" else item) + ">=" + PACKAGE_COMPONENTS[item][1] for item in components]
    if semantic and SEMANTIC_REQUIREMENT not in result:
        result.append(SEMANTIC_REQUIREMENT)
    return result


def _validate_selection(request):
    if not isinstance(request, dict):
        raise ValueError("Upgrade selection must be a JSON object.")
    extra = set(request) - {"mode", "components", "upgrade_pip", "upgrade_python", "include_semantic"}
    if extra:
        raise ValueError("Unknown upgrade settings: " + ", ".join(sorted(map(str, extra))))
    mode = request.get("mode", "required")
    if not isinstance(mode, str) or mode not in {"required", "selected"}:
        raise ValueError("Upgrade mode must be required or selected.")
    values = request.get("components", [])
    if not isinstance(values, list) or len(values) > len(REQUIRED_IDS) or any(not isinstance(item, str) for item in values):
        raise ValueError("Components must be a list of allowlisted package IDs.")
    if len(set(values)) != len(values) or any(item not in PACKAGE_COMPONENTS for item in values):
        raise ValueError("Choose unique package IDs from the displayed required-component list.")
    flags = {}
    for name in ("upgrade_pip", "upgrade_python", "include_semantic"):
        value = request.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(name + " must be true or false.")
        flags[name] = value
    if mode == "required":
        if values and set(values) != set(REQUIRED_IDS):
            raise ValueError("Required mode upgrades the complete required environment; use selected mode for individual packages.")
        components = list(REQUIRED_IDS)
    else:
        components = [item for item in REQUIRED_IDS if item in values]
    if not components and not any(flags.values()):
        raise ValueError("Select at least one package, pip, Python runtime or semantic dependency update.")
    return {"mode": mode, "components": components, **flags}


def validate_upgrade_plan(plan: dict) -> dict:
    """Reject edited plans, arbitrary packages/URLs/commands and version pins.

    A copied validated dictionary is returned. Startup must call this again;
    the API's earlier validation is never a trust boundary for a disk file.
    """
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        raise ValueError("The pending upgrade plan has an unsupported schema or unexpected fields.")
    if plan["schema_version"] != "1.0" or plan["apply_on"] != "next_start" or plan["status"] != "queued":
        raise ValueError("Only schema 1.0 upgrades queued for next_start are supported.")
    if not isinstance(plan["plan_id"], str) or not re.fullmatch(r"UPGRADE-[a-f0-9]{32}", plan["plan_id"]):
        raise ValueError("Invalid upgrade plan ID.")
    if not isinstance(plan["created_at"], str):
        raise ValueError("Invalid upgrade creation time.")
    try:
        parsed = datetime.fromisoformat(plan["created_at"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ValueError("Upgrade creation time must include a valid timezone.") from exc
    selected = _validate_selection({key: plan[key] for key in ("mode", "components", "upgrade_pip", "upgrade_python", "include_semantic")})
    if selected["components"] != plan["components"]:
        raise ValueError("Upgrade components are not in canonical allowlist order.")
    expected = _requirements(selected["components"], selected["include_semantic"])
    if plan["requirements"] != expected or plan["project_extras"] != ["ui"]:
        raise ValueError("Upgrade requirements must exactly match the curated package allowlist.")
    if plan["python_runtime"] != (TARGET_PYTHON if selected["upgrade_python"] else "keep"):
        raise ValueError("Python runtime must match the fixed supported runtime action.")
    if not isinstance(plan["hardware_summary"], dict):
        raise ValueError("Upgrade hardware summary must be an object.")
    for name in ("rationale", "warnings"):
        if not isinstance(plan[name], list) or len(plan[name]) > 30 or any(not isinstance(value, str) or len(value) > 2000 for value in plan[name]):
            raise ValueError("Upgrade rationale and warnings must be bounded text lists.")
    # Ensures even nested metadata cannot smuggle NaN/objects into the receipt.
    try:
        encoded = json.dumps(plan, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Upgrade plan must contain finite JSON values.") from exc
    if len(encoded) > 32000:
        raise ValueError("Upgrade plan is too large.")
    return json.loads(encoded)


def build_install_requirements(plan: dict) -> list[str]:
    """Return package arguments, never a shell command or caller-supplied URL."""
    return list(validate_upgrade_plan(plan)["requirements"])


def _gib(value):
    return round(value / (1024 ** 3), 2) if value is not None else None


def _memory():
    if os.name == "nt":
        try:
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
                            ("extended", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {"total_gib": _gib(status.total), "available_gib": _gib(status.available), "source": "Windows GlobalMemoryStatusEx"}
        except (OSError, AttributeError):
            pass
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        return {"total_gib": _gib(page * os.sysconf("SC_PHYS_PAGES")),
                "available_gib": _gib(page * os.sysconf("SC_AVPHYS_PAGES")), "source": "OS page counters"}
    except (AttributeError, OSError, ValueError):
        return {"total_gib": None, "available_gib": None, "source": "unavailable"}


def _gpu():
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            result = subprocess.run([executable, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            devices = []
            for line in result.stdout[:10000].splitlines()[:16]:
                name, memory = line.rsplit(",", 1)
                value = float(memory.strip()) / 1024
                if math.isfinite(value) and value > 0:
                    devices.append({"name": name.strip(), "memory_gib": round(value, 2)})
            if result.returncode == 0 and devices:
                return {"status": "detected", "devices": devices, "note": "NVIDIA memory was reported. Driver, CUDA and model compatibility are not guaranteed."}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return {"status": "unknown", "devices": [], "note": "No usable NVIDIA report. Other GPUs may exist; GPU acceleration and available VRAM are unknown."}


def _cpu_model():
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
        except OSError:
            pass
    return platform.processor() or "Unknown CPU model"


def inspect_hardware(project_root: Path | None = None) -> dict:
    root = Path(project_root or PROJECT).resolve()
    try:
        disk = shutil.disk_usage(root)
        disk_info = {"path": str(root), "free_gib": _gib(disk.free), "total_gib": _gib(disk.total)}
    except OSError:
        disk_info = {"path": str(root), "free_gib": None, "total_gib": None}
    return {"os": platform.system(), "os_version": platform.version(), "architecture": platform.machine(),
            "cpu": {"model": _cpu_model(), "logical_cores": os.cpu_count()},
            "memory": _memory(), "disk": disk_info, "gpu": _gpu()}


def hardware_recommendations(hardware: dict) -> dict:
    memory = hardware.get("memory", {}).get("total_gib")
    free = hardware.get("disk", {}).get("free_gib")
    architecture = str(hardware.get("architecture", "")).lower()
    wide = architecture in {"amd64", "x86_64", "arm64", "aarch64"}
    known = isinstance(memory, (float, int)) and isinstance(free, (float, int))
    semantic = known and wide and memory >= 15 and free >= 8
    windows_build = re.findall(r"\d+", str(hardware.get("os_version", "")))
    supported_ai_os = (hardware.get("os") in {"Darwin", "Linux"}
                       or hardware.get("os") == "Windows" and bool(windows_build) and int(windows_build[-1]) >= 19045)
    local_ai = known and wide and memory >= 15 and free >= 16 and supported_ai_os
    if not known:
        tier = "unknown"
        rationale = ["RAM or free disk could not be read. Confirm capacity before loading the required real AI and embedding models."]
    elif memory < 8 or free < 4:
        tier = "constrained"
        rationale = ["Resources are limited. Free disk and memory, reduce capture sizes, and select a smaller real language model or use a more capable computer."]
    elif semantic:
        tier = "standard" if memory < 30 else "expanded"
        rationale = ["Resources meet the planning estimates for the required semantic embedding model and a small local language model; actual model memory needs still apply."]
    else:
        tier = "lightweight"
        rationale = ["The project requires real AI and semantic embeddings. Use a smaller real language model and confirm enough available memory and disk before loading it."]
    gpu = hardware.get("gpu", {})
    gpu_memory = max((device.get("memory_gib", 0) for device in gpu.get("devices", [])), default=0)
    ai = "Use a real quantized language model sized for available RAM; a smaller 1B-3B model can reduce memory demand. CPU inference can be slow."
    if gpu_memory >= 8 and local_ai:
        ai = "A small quantized model may benefit from the reported GPU. Confirm current driver/runtime compatibility and model memory needs first."
    available = hardware.get("memory", {}).get("available_gib")
    warnings = ["Resource thresholds are conservative planning estimates, not installation, performance or compatibility guarantees.",
                "Real embedding packages and local language-model weights require disk space and an initial download.",
                "Changing embedding providers requires a separate compatible index; this upgrade queue does not change providers or existing data."]
    if isinstance(available, (int, float)) and available < 4:
        warnings.append("Less than 4 GiB RAM is currently available. Close other heavy applications before loading AI models or large captures; available memory changes over time.")
    if not supported_ai_os:
        warnings.append("Ollama OS support is unconfirmed here. Confirm the official platform requirements before loading the real model runtime.")
    return {"tier": tier, "rationale": rationale, "semantic_suitable": bool(semantic), "local_ai_suitable": bool(local_ai),
            "local_ai_guidance": ai if local_ai else "Confirm RAM, free disk and OS support, then use a smaller real model or a computer with sufficient resources. Real AI is required; missing resources must be resolved before model use.",
            "warnings": warnings}


def _python_action_allowed(hardware):
    return hardware.get("os") == "Windows" and str(hardware.get("architecture", "")).lower() in {"amd64", "x86_64", "arm64", "aarch64"}


def build_upgrade_plan(request: dict, hardware: dict | None = None) -> dict:
    selected = _validate_selection(request)
    hardware = hardware if hardware is not None else inspect_hardware()
    recommendation = hardware_recommendations(hardware)
    if selected["upgrade_python"] and not _python_action_allowed(hardware):
        raise ValueError("The queued private Python runtime is supported only on Windows x64 or ARM64. Use official manual runtime guidance on this platform.")
    rationale = list(recommendation["rationale"])
    if selected["mode"] == "required":
        rationale.append("Upgrade the complete set of directly required core and dashboard packages together in a staged environment.")
    else:
        rationale.append("Upgrade only selected direct packages; compatible transitive dependency updates may also be needed.")
    warnings = ["Applied only on the next managed startup after existing FRIB services are stopped. The running environment is not modified.",
                "Dependency resolution, import checks and staged validation reduce risk; application compatibility is not guaranteed by a latest-version label.",
                "Application records, uploaded files, configuration and provider choices remain separate from the environment upgrade."]
    if selected["include_semantic"]:
        warnings.append("Semantic dependency update: sentence-transformers and dependencies can require large downloads. This package update does not change model or provider configuration.")
    if selected["upgrade_python"]:
        warnings.append("Install the allowlisted private Python 3.13.16 runtime from python.org, then validate a replacement environment. System Python is not replaced.")
    plan = {"schema_version": "1.0", "plan_id": "UPGRADE-" + uuid.uuid4().hex, "created_at": _now(),
        "apply_on": "next_start", "status": "queued", **selected,
        "requirements": _requirements(selected["components"], selected["include_semantic"]), "project_extras": ["ui"],
        "python_runtime": TARGET_PYTHON if selected["upgrade_python"] else "keep",
        "hardware_summary": {"os": hardware.get("os"), "architecture": hardware.get("architecture"),
            "ram_gib": hardware.get("memory", {}).get("total_gib"), "free_disk_gib": hardware.get("disk", {}).get("free_gib"), "tier": recommendation["tier"]},
        "rationale": rationale, "warnings": warnings}
    return validate_upgrade_plan(plan)


def _installed(distribution):
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _ai_settings(project_root):
    """Read provider labels without initializing operational storage or models."""
    settings = {"llm_provider": "ollama", "llm_model": "qwen3:8b",
                "embedding_provider": "sentence_transformers", "embedding_model": "all-MiniLM-L6-v2"}
    config_dir = Path(os.getenv("FRIB_CONFIG_DIR", str(Path(project_root) / "config")))
    path = config_dir / "models.yaml"
    if path.is_file():
        try:
            import yaml
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for section, prefix in (("llm", "llm"), ("embeddings", "embedding")):
                values = payload.get(section, {})
                for name in ("provider", "model"):
                    if isinstance(values.get(name), str):
                        settings[f"{prefix}_{name}"] = values[name]
        except Exception as exc:
            settings["configuration_error"] = f"Model configuration could not be read: {type(exc).__name__}"
    for key, variable in (("llm_provider", "FRIB_LLM_PROVIDER"), ("llm_model", "FRIB_LLM_MODEL"),
                          ("embedding_provider", "FRIB_EMBEDDING_PROVIDER"), ("embedding_model", "FRIB_EMBEDDING_MODEL")):
        if variable in os.environ:
            settings[key] = os.environ[variable]
    return settings


def _ollama_binary(project_root):
    """Find the persistent runtime as well as older project installations."""
    configured = os.getenv("FRIB_OLLAMA_BIN")
    if configured:
        return shutil.which(configured)
    from frib_ds.ai_storage import ai_home
    tool_dirs = [ai_home() / "tools" / "ollama", Path(project_root) / ".frib" / "tools" / "ollama"]
    candidates = [candidate for tool_dir in tool_dirs for candidate in (
        tool_dir / "ollama", tool_dir / "ollama.exe",
        tool_dir / "Ollama.app" / "Contents" / "Resources" / "ollama",
        tool_dir.parent / "Ollama.app" / "Contents" / "Resources" / "ollama")]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ollama")


def _meets_minimum(version, minimum):
    if version is None:
        return False
    try:
        from packaging.version import Version
        return Version(version) >= Version(minimum)
    except (ImportError, ValueError):
        return None


def _reparse(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


class SystemManager:
    def __init__(self, project_root=None):
        self.project_root = Path(project_root or PROJECT).resolve()
        self.state_dir = self.project_root / ".frib"
        self.pending_path = self.state_dir / "pending-upgrade.json"
        self.last_result_path = self.state_dir / "last-upgrade.json"
        self.active_pointer_path = self.state_dir / "active-environment.json"
        self.latest_versions = None

    def _safe_state(self, create=False):
        if _reparse(self.state_dir) or (self.state_dir.exists() and not self.state_dir.is_dir()):
            raise ValueError("The .frib upgrade-state directory must be an ordinary project-owned directory.")
        if create:
            self.state_dir.mkdir(exist_ok=True)
        for path in (self.pending_path, self.last_result_path, self.active_pointer_path):
            if _reparse(path) or (path.exists() and (not path.is_file() or path.stat().st_nlink > 1)):
                raise ValueError("Upgrade state files must be ordinary project-owned files.")

    def runtime_info(self, upgrade=None):
        self._safe_state()
        pointer, error, active = None, None, None
        if self.active_pointer_path.is_file():
            try:
                if self.active_pointer_path.stat().st_size > 16000:
                    raise ValueError("The active environment pointer is too large.")
                value = json.loads(self.active_pointer_path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("schema_version") != "1.0" or not isinstance(value.get("path"), str) or not re.fullmatch(r"environments/ENV-[a-f0-9]{32}", value["path"]):
                    raise ValueError("The active environment pointer is invalid; startup will require a valid managed pointer.")
                pointer = {key: value.get(key) for key in ("schema_version", "path", "python_version", "validated_at", "plan_id")}
                active = str(self.state_dir / value["path"])
            except (ValueError, OSError) as exc:
                error = str(exc)
        last = (upgrade or {}).get("last_result") or {}
        previous = last.get("previous_python")
        return {"executable": sys.executable, "python_version": platform.python_version(),
                "active_pointer_path": str(self.active_pointer_path), "active_environment": pointer,
                "active_environment_path": active, "active_pointer_error": error,
                "previous_python": previous if isinstance(previous, str) else None,
                "legacy_environment_path": str(self.project_root / ".venv")}

    def upgrade_status(self):
        self._safe_state()
        pending, error, last = None, None, None
        if self.pending_path.is_file():
            try:
                if self.pending_path.stat().st_size > 32000:
                    raise ValueError("Pending upgrade file exceeds its size limit.")
                pending = validate_upgrade_plan(json.loads(self.pending_path.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                error = str(exc)
        if self.last_result_path.is_file():
            try:
                if self.last_result_path.stat().st_size <= 64000:
                    last = json.loads(self.last_result_path.read_text(encoding="utf-8"))
                    if not isinstance(last, dict):
                        last = None
            except (ValueError, OSError):
                pass
        return {"pending": pending, "pending_error": error, "last_result": last}

    def queue_plan(self, request):
        plan = build_upgrade_plan(request, inspect_hardware(self.project_root))
        self._safe_state(create=True)
        descriptor, name = tempfile.mkstemp(prefix="pending-", suffix=".tmp", dir=self.state_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(plan, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Recheck immediately before replacement; no install happens here.
            self._safe_state()
            os.replace(name, self.pending_path)
        finally:
            Path(name).unlink(missing_ok=True)
        return {"queued": True, "plan": plan}

    def cancel_plan(self):
        self._safe_state()
        existed = self.pending_path.is_file()
        self.pending_path.unlink(missing_ok=True)
        return {"cancelled": existed, "pending": None}

    def inventory(self):
        hardware = inspect_hardware(self.project_root)
        recommendation = hardware_recommendations(hardware)
        ai = _ai_settings(self.project_root)
        components = []
        for item, (name, minimum, category, purpose) in PACKAGE_COMPONENTS.items():
            installed = _installed(item)
            meets = _meets_minimum(installed, minimum)
            components.append({"id": item, "name": name, "category": category, "required": True,
                "purpose": purpose, "installed_version": installed, "minimum_version": minimum,
                "status": "missing" if installed is None else "below_minimum" if meets is False else "installed",
                "upgradeable": True, "choices": [{"id": "upgrade", "label": "Queue package update", "enabled": True,
                    "description": "Resolve a supported available release on next start inside a staged environment.",
                    "reason": "This package is in the curated required allowlist. Resolver/import validation is still required."}]})
        python_allowed = _python_action_allowed(hardware)
        components.append({"id": "python", "name": "Python runtime", "category": "runtime", "required": True,
            "purpose": "Run the application and its private scientific/dashboard environment.", "installed_version": platform.python_version(),
            "minimum_version": "3.11", "recommended_version": TARGET_PYTHON, "status": "tested_branch" if (3, 11) <= sys.version_info[:2] <= (3, 13) else "review_runtime",
            "upgradeable": python_allowed, "guidance_url": PYTHON_RELEASE_URL,
            "choices": [{"id": "upgrade", "label": "Queue private Python 3.13.16", "enabled": python_allowed,
                "description": "Install the fixed official Windows x64/ARM64 runtime privately on next start; keep system Python unchanged.",
                "reason": "Windows 64-bit private-runtime bootstrap is supported." if python_allowed else "Use an official Python 3.11-3.13 runtime manually on this platform; newer feature branches are not claimed tested."}]})
        components.append({"id": "pip", "name": "pip", "category": "installer", "required": True,
            "purpose": "Resolve and install dependencies in the staged private environment.", "installed_version": _installed("pip"), "minimum_version": None,
            "status": "installed" if _installed("pip") else "missing", "upgradeable": True,
            "choices": [{"id": "upgrade", "label": "Queue pip update", "enabled": True,
                "description": "Upgrade pip only in the replacement environment during next startup.", "reason": "The running installer/environment are not modified."}]})
        ollama = _ollama_binary(self.project_root)
        ollama_version = None
        if ollama:
            try:
                output = subprocess.run([ollama, "--version"], capture_output=True, text=True, timeout=2, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if output.returncode == 0:
                    ollama_version = (output.stdout or output.stderr).strip()[:200]
            except (OSError, subprocess.TimeoutExpired):
                pass
        ollama_required = ai["llm_provider"] == "ollama"
        components.append({"id": "ollama", "name": "Ollama local AI runtime", "category": "ai", "required": ollama_required,
            "purpose": f"Serve the configured real language model ({ai['llm_model']})." if ollama_required else "Local language-model runtime; a different real provider is configured.",
            "installed_version": ollama_version, "binary_path": ollama, "minimum_version": None,
            "status": "available" if ollama else "missing" if ollama_required else "not_configured", "upgradeable": False,
            "guidance_url": "https://docs.ollama.com", "choices": [{"id": "manual", "label": "Review local AI guidance", "enabled": False,
                "description": recommendation["local_ai_guidance"], "reason": "The project launcher manages the configured real runtime and model; pip package upgrades do not update Ollama."}]})
        components.append({"id": "frib-decision-support", "name": "FRIB project source", "category": "application", "required": True,
            "purpose": "The local application source being run; required upgrades reinstall this reviewed local source.",
            "installed_version": _installed("frib-decision-support"), "minimum_version": None, "status": "local_source", "upgradeable": False,
            "choices": [{"id": "manual", "label": "Use a reviewed project release", "enabled": False,
                "description": "Back up the workspace and apply a reviewed source release separately from package upgrades.", "reason": "This queue cannot verify or download a new application source release."}]})
        components.append({"id": "sqlite", "name": "SQLite", "category": "runtime", "required": True,
            "purpose": "Persist events, analyses, reviews, document catalogs and local retrieval vectors.",
            "installed_version": sqlite3.sqlite_version, "minimum_version": None, "status": "installed", "upgradeable": False,
            "choices": [{"id": "bundled", "label": "Updated with the Python runtime", "enabled": False,
                "description": "SQLite is bundled with Python; use the private Python runtime upgrade to change its bundled library.",
                "reason": "Replacing sqlite3 separately with pip is not a supported upgrade action."}]})
        upgrade = self.upgrade_status()
        return {"schema_version": "1.0", "checked_at": _now(), "hardware": hardware, "recommendations": recommendation,
                "components": components, "upgrade": upgrade, "runtime": self.runtime_info(upgrade), "ai": ai, "latest": self.latest_versions,
                "network_checked": False, "runtime_policy": "Python 3.11-3.13 are the tested branches; fixed Windows x64/ARM64 private-runtime target is 3.13.16."}

    def check_latest_versions(self):
        """Explicit official-PyPI metadata check, bounded and never an install."""
        checked = _now()
        identifiers = [*REQUIRED_IDS, "pip"]

        def check(item):
            row = {"id": item, "installed_version": _installed(item), "latest_version": None,
                   "status": "unavailable", "requires_python": None, "python_compatible": None, "error": None}
            try:
                request = Request(f"https://pypi.org/pypi/{item}/json", headers={"User-Agent": "FRIB-System-Inventory/1.0", "Accept": "application/json"})
                with urlopen(request, timeout=3) as response:
                    # Official fixed URL only; reject an unexpected redirect host.
                    if not response.geturl().startswith("https://pypi.org/pypi/"):
                        raise ValueError("PyPI metadata redirected outside the official endpoint.")
                    contents = response.read(10_000_001)
                if len(contents) > 10_000_000:
                    raise ValueError("PyPI metadata exceeds the inspection limit.")
                payload = json.loads(contents)
                info = payload["info"]
                version, requires = info["version"], info.get("requires_python")
                if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+!_-]{1,100}", version):
                    raise ValueError("PyPI did not provide a valid version label.")
                if requires is not None and not isinstance(requires, str):
                    raise ValueError("PyPI did not provide a valid Python requirement.")
                compatible = None
                if requires:
                    try:
                        from packaging.specifiers import SpecifierSet
                        compatible = platform.python_version() in SpecifierSet(requires)
                    except (ImportError, ValueError):
                        pass
                row.update(latest_version=version, status="ok", requires_python=requires, python_compatible=compatible)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: metadata unavailable; current installed version is unchanged."
            return row

        with ThreadPoolExecutor(max_workers=5) as executor:
            versions = list(executor.map(check, identifiers))
        self.latest_versions = {"checked_at": checked, "source": "https://pypi.org", "versions": versions, "network_checked": True,
            "note": "Latest labels are informational. They are not pinned into plans; pip resolves Python/platform/dependency-compatible releases at next startup."}
        return self.latest_versions


def get_system_manager():
    # State is small and process-local; this cache stores only explicitly checked
    # version metadata, never application data or credentials.
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = SystemManager()
    return _MANAGER


_MANAGER = None
