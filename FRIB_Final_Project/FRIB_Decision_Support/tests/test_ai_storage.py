"""Permanent AI assets stay inside an ordinary, locked user storage directory."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from frib_ds import ai_storage


@pytest.fixture
def storage(tmp_path):
    root = tmp_path / "permanent-ai"
    return root, {"FRIB_AI_HOME": str(root)}


def test_directory_creation_and_atomic_receipt_stay_inside_configured_root(storage):
    root, env = storage
    models = ai_storage.ensure_directory(root / "models/ollama", env)
    assert models == root / "models/ollama" and models.is_dir()
    receipt = root / "real-ai-validation.json"
    ai_storage.atomic_json(receipt, {"mock_ai": False, "model": "qwen3:8b"}, env)
    assert json.loads(receipt.read_text(encoding="utf-8")) == {"mock_ai": False, "model": "qwen3:8b"}
    ai_storage.atomic_json(receipt, {"model": "replacement"}, env)
    assert json.loads(receipt.read_text(encoding="utf-8")) == {"model": "replacement"}
    assert list(root.glob("*.tmp")) == []
    if os.name != "nt":
        assert models.stat().st_mode & 0o777 == 0o700


def test_failed_json_write_preserves_previous_receipt_and_cleans_temporary_file(storage):
    root, env = storage
    receipt = root / "real-ai-validation.json"
    ai_storage.atomic_json(receipt, {"valid": True}, env)
    original = receipt.read_bytes()
    with pytest.raises(ValueError):
        ai_storage.atomic_json(receipt, {"bad": float("nan")}, env)
    assert receipt.read_bytes() == original
    assert list(root.glob("*.tmp")) == []


@pytest.mark.parametrize("kind", ["outside", "traversal"])
def test_path_escape_cannot_create_or_replace_files(storage, tmp_path, kind):
    root, env = storage
    path = tmp_path / "outside.json" if kind == "outside" else root / "../outside.json"
    with pytest.raises(RuntimeError, match="outside|traversal"):
        ai_storage.atomic_json(path, {"bad": True}, env)
    assert not (tmp_path / "outside.json").exists()
    assert not root.exists()


def test_storage_root_cannot_use_parent_traversal(tmp_path):
    root = tmp_path / "parent/../permanent-ai"
    with pytest.raises(RuntimeError, match="traversal"):
        ai_storage.guard_path(root / "receipt.json", {"FRIB_AI_HOME": str(root)})


@pytest.mark.parametrize("linked_part", ["root", "ancestor", "child"])
def test_symlinked_storage_component_cannot_redirect_writes(tmp_path, linked_part):
    outside = tmp_path / "outside"
    outside.mkdir()
    if linked_part == "root":
        root = tmp_path / "permanent-ai"
        root.symlink_to(outside, target_is_directory=True)
        destination = root / "receipt.json"
    elif linked_part == "ancestor":
        ancestor = tmp_path / "redirect"
        ancestor.symlink_to(outside, target_is_directory=True)
        root = ancestor / "permanent-ai"
        destination = root / "receipt.json"
    else:
        root = tmp_path / "permanent-ai"
        root.mkdir()
        child = root / "models"
        child.symlink_to(outside, target_is_directory=True)
        destination = child / "receipt.json"
    with pytest.raises(RuntimeError, match="linked|redirected"):
        ai_storage.atomic_json(destination, {"bad": True}, {"FRIB_AI_HOME": str(root)})
    assert list(outside.iterdir()) == []


def test_hardlinked_receipt_cannot_modify_an_external_file(storage, tmp_path):
    root, env = storage
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("original", encoding="utf-8")
    receipt = root / "receipt.json"
    os.link(outside, receipt)
    with pytest.raises(RuntimeError, match="linked|redirected"):
        ai_storage.atomic_json(receipt, {"bad": True}, env)
    assert outside.read_text(encoding="utf-8") == "original"


@pytest.mark.skipif(os.name == "nt", reason="POSIX special file fixture")
def test_special_files_are_rejected(storage):
    root, env = storage
    root.mkdir()
    pipe = root / "pipe"
    os.mkfifo(pipe)
    with pytest.raises(RuntimeError, match="ordinary"):
        ai_storage.guard_path(pipe, env)


def test_shared_setup_lock_is_reentrant_and_released_after_an_exception(storage):
    root, env = storage
    with pytest.raises(RuntimeError, match="fixture error"):
        with ai_storage.AIStorageLock(env) as first:
            with ai_storage.AIStorageLock(env) as second:
                assert first.path == second.path == root / "setup.lock"
            raise RuntimeError("fixture error")
    with ai_storage.AIStorageLock(env):
        pass


def test_shared_setup_lock_blocks_other_threads(storage):
    _, env = storage
    def other_setup():
        try:
            with ai_storage.AIStorageLock(env):
                return "unexpectedly acquired"
        except RuntimeError:
            return "blocked"
    with ai_storage.AIStorageLock(env), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(other_setup).result(timeout=5) == "blocked"
    assert other_setup() == "unexpectedly acquired"


def test_shared_setup_lock_blocks_other_project_processes_and_releases(storage):
    _, env = storage
    source_dir = Path(ai_storage.__file__).resolve().parents[1]
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from frib_ds.ai_storage import AIStorageLock\n"
        "try:\n"
        " with AIStorageLock(): print('acquired')\n"
        "except RuntimeError:\n"
        " print('blocked')\n"
    )
    child_env = dict(os.environ, **env)
    def child():
        result = subprocess.run([sys.executable, "-S", "-c", script, str(source_dir)], env=child_env,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    with ai_storage.AIStorageLock(env):
        assert child() == "blocked"
    assert child() == "acquired"
