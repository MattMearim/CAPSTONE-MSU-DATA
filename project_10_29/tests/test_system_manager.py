"""Hardware inventory and next-start upgrades never mutate the live app."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from frib_ds.api import main as api
from frib_ds import system_manager as system


def hardware(ram=15.73, free=50, architecture="AMD64", operating_system="Windows", version="10.0.26100"):
    return {"os": operating_system, "os_version": version, "architecture": architecture,
            "cpu": {"model": "Fictional CPU", "logical_cores": 8},
            "memory": {"total_gib": ram, "available_gib": 8, "source": "test"},
            "disk": {"free_gib": free, "total_gib": 100, "path": "test"},
            "gpu": {"status": "unknown", "devices": [], "note": "Not detected"}}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    instance = system.SystemManager(tmp_path)
    monkeypatch.setattr(system, "inspect_hardware", lambda *args, **kwargs: hardware())
    monkeypatch.setattr(api, "get_system_manager", lambda: instance)
    monkeypatch.setattr(api, "get_services", lambda: pytest.fail("System-only tests must not access saved operational data"))
    return instance


@pytest.fixture
def client(manager):
    # Not entering the lifespan context is deliberate: these routes must not
    # hydrate or recover any user's operational data merely to inspect a host.
    instance = TestClient(api.app)
    try:
        yield instance
    finally:
        instance.close()


@pytest.mark.parametrize("machine,tier,semantic,local_ai", [
    (hardware(), "standard", True, True),
    (hardware(ram=32), "expanded", True, True),
    (hardware(ram=4), "constrained", False, False),
    (hardware(ram=8), "lightweight", False, False),
    (hardware(free=3), "constrained", False, False),
    (hardware(ram=None), "unknown", False, False),
    (hardware(architecture="x86"), "lightweight", False, False),
    (hardware(version="10.0.19044"), "standard", True, False),
    (hardware(version="unknown"), "standard", True, False),
])
def test_hardware_choices_reflect_confirmed_resources_and_os(machine, tier, semantic, local_ai):
    result = system.hardware_recommendations(machine)
    assert result["tier"] == tier
    assert result["semantic_suitable"] is semantic
    assert result["local_ai_suitable"] is local_ai
    assert "guarantee" in " ".join(result["warnings"])


def test_available_ram_warning_does_not_claim_static_capacity():
    machine = hardware()
    machine["memory"]["available_gib"] = 1
    result = system.hardware_recommendations(machine)
    assert result["semantic_suitable"] is True
    assert any("currently available" in warning for warning in result["warnings"])


@pytest.mark.parametrize("selection", [
    {"mode": "selected", "components": ["numpy"]},
    {"mode": "selected", "components": [], "upgrade_pip": True},
    {"mode": "selected", "components": [], "upgrade_python": True},
    {"mode": "selected", "components": [], "include_semantic": True},
    {"mode": "required", "upgrade_pip": True, "upgrade_python": True},
])
def test_selected_pip_runtime_optional_and_coherent_plans_have_curated_arguments(selection):
    plan = system.build_upgrade_plan(selection, hardware())
    assert system.validate_upgrade_plan(plan) == plan
    arguments = system.build_install_requirements(plan)
    assert all("http" not in item and ";" not in item and " " not in item for item in arguments)
    assert plan["apply_on"] == "next_start" and plan["status"] == "queued"
    assert plan["python_runtime"] == ("3.13.16" if selection.get("upgrade_python") else "keep")
    assert (system.SEMANTIC_REQUIREMENT in arguments) == bool(selection.get("include_semantic"))
    if selection["mode"] == "required":
        assert set(plan["components"]) == set(system.REQUIRED_IDS)
    else:
        assert plan["components"] == selection["components"]


@pytest.mark.parametrize("selection", [
    {"mode": "selected", "components": []},
    {"mode": "selected", "components": ["numpy; calc.exe"]},
    {"mode": "selected", "components": ["https://evil.invalid/package.whl"]},
    {"mode": "selected", "components": ["numpy==999"]},
    {"mode": "selected", "components": ["sentence-transformers"]},
    {"mode": "selected", "components": ["numpy", "numpy"]},
    {"mode": "selected", "components": [{}]},
    {"mode": [], "components": []},
    {"mode": "required", "components": ["numpy"]},
    {"mode": "required", "upgrade_pip": "yes"},
    {"mode": "required", "command": "pip install whatever"},
    None,
])
def test_untrusted_selection_cannot_supply_commands_urls_versions_or_invalid_shapes(selection):
    with pytest.raises(ValueError):
        system.build_upgrade_plan(selection, hardware())


@pytest.mark.parametrize("field,value", [
    ("requirements", ["requests @ https://example.invalid/evil.whl"]),
    ("components", ["numpy;echo"]),
    ("project_extras", ["dev"]),
    ("python_runtime", "3.15.0"),
    ("status", "apply_now"),
    ("created_at", "not-a-date"),
    ("hardware_summary", {"free_disk": float("nan")}),
    ("extra_command", "calc.exe"),
])
def test_bootstrap_validator_rejects_tampered_disk_plans(field, value):
    plan = system.build_upgrade_plan({"mode": "required"}, hardware())
    plan[field] = value
    with pytest.raises(ValueError):
        system.validate_upgrade_plan(plan)


def test_optional_downloads_and_runtime_are_disabled_when_inappropriate():
    with pytest.raises(ValueError, match="reported RAM"):
        system.build_upgrade_plan({"mode": "selected", "include_semantic": True}, hardware(ram=8))
    with pytest.raises(ValueError, match="Windows"):
        system.build_upgrade_plan({"mode": "selected", "upgrade_python": True}, hardware(operating_system="Linux"))
    assert system.build_upgrade_plan({"mode": "selected", "upgrade_python": True}, hardware(architecture="ARM64"))["upgrade_python"] is True


def test_queue_replace_cancel_only_changes_project_upgrade_receipt(manager, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    evidence = data / "original.txt"
    evidence.write_bytes(b"Saved evidence must be unchanged")
    config = tmp_path / "config.yaml"
    config.write_text("provider: user-choice\n", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Queue must never execute an installer"))
    first = manager.queue_plan({"mode": "selected", "components": ["numpy"]})["plan"]
    assert manager.upgrade_status()["pending"] == first
    second = manager.queue_plan({"mode": "selected", "upgrade_pip": True})["plan"]
    assert second["plan_id"] != first["plan_id"]
    assert manager.upgrade_status()["pending"] == second
    assert second["components"] == [] and second["upgrade_pip"] is True
    assert manager.cancel_plan() == {"cancelled": True, "pending": None}
    assert manager.cancel_plan() == {"cancelled": False, "pending": None}
    assert evidence.read_bytes() == b"Saved evidence must be unchanged"
    assert config.read_text(encoding="utf-8") == "provider: user-choice\n"


def test_bad_pending_file_is_reported_and_can_be_cancelled(manager):
    manager.state_dir.mkdir()
    manager.pending_path.write_text("not JSON", encoding="utf-8")
    result = manager.upgrade_status()
    assert result["pending"] is None and result["pending_error"]
    assert manager.cancel_plan()["cancelled"] is True


def test_upgrade_state_symlink_cannot_redirect_writes(manager, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    try:
        manager.state_dir.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("This account cannot create a directory symlink")
    with pytest.raises(ValueError, match="ordinary"):
        manager.queue_plan({"mode": "required"})
    assert list(external.iterdir()) == []


def test_inventory_lists_every_required_component_and_builtin_sqlite_without_network(manager, monkeypatch):
    monkeypatch.setattr(system, "urlopen", lambda *a, **k: pytest.fail("Inventory must be offline"))
    monkeypatch.setattr(system.shutil, "which", lambda *a, **k: None)
    inventory = manager.inventory()
    by_id = {entry["id"]: entry for entry in inventory["components"]}
    assert set(system.REQUIRED_IDS).issubset(by_id)
    assert {"pip", "python", "sqlite", "ollama", "sentence-transformers"}.issubset(by_id)
    assert all(entry["purpose"] and entry["choices"] for entry in by_id.values())
    assert by_id["sqlite"]["installed_version"] == system.sqlite3.sqlite_version
    assert by_id["sqlite"]["upgradeable"] is False
    assert by_id["python"]["recommended_version"] == "3.13.16"
    assert inventory["network_checked"] is False
    assert inventory["upgrade"]["pending"] is None
    assert inventory["runtime"]["executable"] == sys.executable


def test_runtime_pointer_and_previous_interpreter_are_reported_without_following_arbitrary_paths(manager):
    manager.state_dir.mkdir()
    pointer = {"schema_version": "1.0", "path": "environments/ENV-" + "a" * 32,
               "python_version": "3.13.16", "validated_at": "2026-10-12T12:00:00Z", "plan_id": None}
    manager.active_pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    manager.last_result_path.write_text(json.dumps({"status": "applied", "previous_python": str(manager.project_root / ".venv/Scripts/python.exe")}), encoding="utf-8")
    info = manager.runtime_info(manager.upgrade_status())
    assert info["active_environment"] == pointer
    assert info["previous_python"].endswith("python.exe")
    manager.active_pointer_path.write_text(json.dumps({"schema_version": "1.0", "path": "../../outside"}), encoding="utf-8")
    invalid = manager.runtime_info()
    assert invalid["active_environment_path"] is None and invalid["active_pointer_error"]


def test_allowlist_covers_current_core_and_dashboard_requirements():
    import tomllib
    project = Path(system.__file__).resolve().parents[2]
    declared = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = declared["dependencies"] + declared["optional-dependencies"]["ui"]
    names = {item.split(">=")[0].split("[")[0].lower() for item in requirements}
    assert names == set(system.REQUIRED_IDS)
    plan = system.build_upgrade_plan({"mode": "required"}, hardware())
    assert {item.lower() for item in plan["requirements"]} == {item.lower() for item in requirements}


class MetadataResponse:
    def __init__(self, contents, url="https://pypi.org/pypi/numpy/json"):
        self.contents, self.url = contents, url
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, count):
        return self.contents[:count]
    def geturl(self):
        return self.url


def test_latest_check_uses_only_fixed_official_urls_timeout_and_python_metadata(manager, monkeypatch):
    requests = []
    def fake(request, timeout):
        requests.append((request.full_url, timeout))
        contents = json.dumps({"info": {"version": "99.2.1", "requires_python": ">=3.99"}}).encode()
        return MetadataResponse(contents, request.full_url)
    monkeypatch.setattr(system, "urlopen", fake)
    result = manager.check_latest_versions()
    assert result["network_checked"] is True and result["source"] == "https://pypi.org"
    assert len(requests) == len(system.REQUIRED_IDS) + 2
    assert all(url.startswith("https://pypi.org/pypi/") and timeout == 3 for url, timeout in requests)
    assert all(entry["latest_version"] == "99.2.1" and entry["python_compatible"] is False for entry in result["versions"])
    assert manager.upgrade_status()["pending"] is None


@pytest.mark.parametrize("failure", ["timeout", "bad_json", "oversized", "redirect"])
def test_latest_check_is_truthful_for_offline_or_invalid_metadata(manager, monkeypatch, failure):
    def fake(request, timeout):
        if failure == "timeout":
            raise socket.timeout("offline")
        if failure == "bad_json":
            return MetadataResponse(b"not JSON")
        if failure == "oversized":
            return MetadataResponse(b" " * 10_000_001)
        return MetadataResponse(b"{}", "https://example.invalid/redirect")
    monkeypatch.setattr(system, "urlopen", fake)
    result = manager.check_latest_versions()
    assert all(entry["status"] == "unavailable" and entry["latest_version"] is None and entry["error"] for entry in result["versions"])
    assert manager.upgrade_status()["pending"] is None


def test_large_valid_pypi_payload_above_two_megabytes_is_supported(manager, monkeypatch):
    payload = json.dumps({"info": {"version": "3.4.5", "requires_python": ">=3.11"}, "releases": {"padding": "x" * 2_100_000}}).encode()
    monkeypatch.setattr(system, "urlopen", lambda request, timeout: MetadataResponse(payload, request.full_url))
    assert all(entry["status"] == "ok" for entry in manager.check_latest_versions()["versions"])


def test_gpu_failure_or_missing_driver_is_unknown_and_bounded(monkeypatch):
    monkeypatch.setattr(system.shutil, "which", lambda name: "fixed-nvidia-smi.exe")
    captured = []
    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        raise subprocess.TimeoutExpired(arguments, 2)
    monkeypatch.setattr(system.subprocess, "run", run)
    result = system._gpu()
    assert result["status"] == "unknown" and result["devices"] == []
    assert captured[0][1]["timeout"] == 2
    assert "shell" not in captured[0][1]


def test_module_can_be_loaded_by_stdlib_only_bootstrap():
    path = Path(system.__file__).resolve()
    source = "import importlib.util,sys; p=importlib.util.spec_from_file_location('upgrade_contract',sys.argv[1]); m=importlib.util.module_from_spec(p); p.loader.exec_module(m); print(len(m.REQUIRED_IDS))"
    result = subprocess.run([sys.executable, "-S", "-c", source, str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "13"


def test_system_api_reads_queues_cancels_without_touching_operational_services(manager, monkeypatch, client):
    monkeypatch.setattr(api, "get_services", lambda: pytest.fail("System inventory must not initialize operational data"))
    monkeypatch.setattr(system.shutil, "which", lambda *a, **k: None)
    inventory = client.get("/system/info")
    assert inventory.status_code == 200 and inventory.json()["network_checked"] is False
    queued = client.post("/system/upgrades/plan", json={"mode": "selected", "components": ["numpy"]})
    assert queued.status_code == 200 and queued.json()["queued"] is True
    assert client.get("/system/info").json()["upgrade"]["pending"]["components"] == ["numpy"]
    assert client.delete("/system/upgrades/plan").json()["cancelled"] is True
    assert client.get("/system/info").json()["upgrade"]["pending"] is None


@pytest.mark.parametrize("payload", [
    {"mode": "selected", "components": ["numpy;calc.exe"]},
    {"mode": "selected", "components": ["numpy", "numpy"]},
    {"mode": "selected", "components": []},
    {"mode": "required", "upgrade_python": "yes"},
    {"mode": "required", "command": "anything"},
    {"mode": "selected", "components": [None]},
])
def test_invalid_api_selections_leave_no_pending_plan(manager, payload, client):
    result = client.post("/system/upgrades/plan", json=payload)
    assert result.status_code in {400, 422}, result.text
    assert manager.upgrade_status()["pending"] is None


def test_latest_api_requires_explicit_post_and_rejects_external_url(manager, monkeypatch, client):
    calls = []
    monkeypatch.setattr(manager, "check_latest_versions", lambda: calls.append(True) or {"network_checked": True, "versions": []})
    assert client.get("/system/versions/check").status_code == 405
    assert client.post("/system/versions/check", json={"url": "https://evil.invalid"}).status_code == 422
    assert calls == []
    assert client.post("/system/versions/check", json={}).json()["network_checked"] is True
    assert calls == [True]
