"""Real-model setup contracts, tested without network or downloaded executables."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tarfile
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request

import pytest

from frib_ds import local_ai


@pytest.fixture(autouse=True)
def shared_ai_home(tmp_path, monkeypatch):
    """Never read or write the person's installed shared model storage."""
    root = tmp_path / "shared-ai"
    monkeypatch.setenv("FRIB_AI_HOME", str(root))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user-home"))
    for variable in ("HF_HOME", "FRIB_EMBEDDING_CACHE", "OLLAMA_MODELS", "HF_HUB_OFFLINE", "FRIB_STARTUP_WINDOW"):
        monkeypatch.delenv(variable, raising=False)
    return root


@pytest.fixture
def models():
    return {"llm": {"provider": "ollama", "model": "qwen3:8b", "ollama_base_url": "http://localhost:11434"},
            "embeddings": {"provider": "sentence_transformers", "model": "all-MiniLM-L6-v2"}}


@pytest.fixture
def real_ai_receipt(models):
    return {"llm": {key: models["llm"][key] for key in ("provider", "model")},
            "embedding": {key: models["embeddings"][key] for key in ("provider", "model")},
            "mock_ai": False, "hash_embeddings": False}


@pytest.fixture
def cached_semantic_model():
    def prepare(cache):
        snapshot = cache / "models--sentence-transformers--all-MiniLM-L6-v2/snapshots/test"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
        (snapshot / "modules.json").write_text("[]", encoding="utf-8")
        (snapshot / "model.safetensors").write_bytes(b"test fixture weights")
        return snapshot
    return prepare


@pytest.fixture
def cached_ollama_model():
    def prepare(root):
        blobs = root / "blobs"
        blobs.mkdir(parents=True)
        layers = []
        for contents in (b"{}", b"fixture language-model weights"):
            digest = hashlib.sha256(contents).hexdigest()
            (blobs / ("sha256-" + digest)).write_bytes(contents)
            layers.append({"digest": "sha256:" + digest, "size": len(contents)})
        manifest = root / "manifests/registry.ollama.ai/library/qwen3/8b"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"config": layers[0], "layers": layers[1:]}), encoding="utf-8")
        return manifest
    return prepare


def test_setup_is_needed_without_a_validation_receipt(models, tmp_path):
    assert local_ai.setup_needed(models, project=tmp_path) is True
    assert not (tmp_path / ".frib").exists()


@pytest.mark.parametrize("contents", ["invalid JSON", "{", "[]", "null", '"receipt"', "12", "true", "{}"])
def test_setup_is_needed_for_corrupt_or_nonobject_receipts(models, tmp_path, contents):
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(contents, encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True
    assert receipt.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("section,key,value", [("llm", "provider", "mock"), ("llm", "provider", "lmstudio"),
                                              ("llm", "model", "qwen3:4b"), ("embedding", "provider", "hash"),
                                              ("embedding", "model", "different-model"), ("llm", "model", None)])
def test_setup_is_needed_when_receipt_models_do_not_match_configuration(models, real_ai_receipt, tmp_path, section, key, value):
    real_ai_receipt[section][key] = value
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True


@pytest.mark.parametrize("flag,value", [("mock_ai", True), ("hash_embeddings", True), ("mock_ai", None),
                                       ("hash_embeddings", "false"), ("mock_ai", 0), ("hash_embeddings", 0)])
def test_setup_is_needed_unless_test_provider_flags_are_literal_false(models, real_ai_receipt, tmp_path, flag, value):
    real_ai_receipt[flag] = value
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True


@pytest.mark.parametrize("missing_key", ["mock_ai", "hash_embeddings", "llm", "embedding"])
def test_setup_is_needed_for_incomplete_receipts(models, real_ai_receipt, tmp_path, missing_key):
    real_ai_receipt.pop(missing_key)
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True


@pytest.mark.parametrize("section", ["llm", "embedding"])
def test_setup_is_needed_for_invalid_nested_receipt_sections(models, real_ai_receipt, tmp_path, section):
    real_ai_receipt[section] = "not an object"
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True


def test_matching_real_model_receipt_skips_download_selection_without_network(models, real_ai_receipt, tmp_path, shared_ai_home, cached_semantic_model):
    cached_semantic_model(shared_ai_home / "cache/huggingface/hub")
    receipt = tmp_path / ".frib/real-ai-validation.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is False
    # Receipt matching is only a setup decision; it does not create weights or prove a server is ready.
    assert not (tmp_path / ".frib/models").exists()
    assert not (tmp_path / ".frib/cache").exists()


@pytest.mark.parametrize("shared", [False, True])
def test_matching_receipt_without_semantic_weights_still_requires_repair(models, real_ai_receipt, tmp_path, shared_ai_home, shared):
    root = shared_ai_home if shared else tmp_path / ".frib"
    root.mkdir()
    (root / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path) is True


def test_matching_shared_receipt_is_reused_by_new_project_copies_without_network(models, real_ai_receipt, tmp_path, shared_ai_home, cached_semantic_model):
    cached_semantic_model(shared_ai_home / "cache/huggingface/hub")
    (shared_ai_home / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    for name in ("FRIB_Final_Project 7", "FRIB_Final_Project 8"):
        project = tmp_path / name
        assert local_ai.setup_needed(models, project=project) is False
        env = local_ai.runtime_environment(project)
        assert env["HF_HUB_OFFLINE"] == "1"
        assert env["OLLAMA_MODELS"] == str(shared_ai_home / "models/ollama")
        assert not project.exists()


@pytest.mark.parametrize("storage_key,variable", [("ollama_models", "OLLAMA_MODELS"), ("embedding_cache", "FRIB_EMBEDDING_CACHE")])
def test_shared_receipt_does_not_reuse_validation_for_a_different_explicit_cache(models, real_ai_receipt, tmp_path, shared_ai_home, cached_semantic_model, monkeypatch, storage_key, variable):
    shared_ai_home.mkdir()
    real_ai_receipt["storage"] = {"ollama_models": str(shared_ai_home / "models/ollama"),
                                  "embedding_cache": str(shared_ai_home / "cache/huggingface/hub")}
    cached_semantic_model(shared_ai_home / "cache/huggingface/hub")
    (shared_ai_home / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path / "new-copy") is False
    monkeypatch.setenv(variable, str(tmp_path / "custom-cache"))
    assert local_ai.setup_needed(models, project=tmp_path / "new-copy") is True
    assert not (tmp_path / "custom-cache").exists()


def test_storage_bound_receipt_requires_repair_after_semantic_weights_disappear(models, real_ai_receipt, tmp_path, shared_ai_home, cached_semantic_model):
    cached_semantic_model(shared_ai_home / "cache/huggingface/hub")
    real_ai_receipt["storage"] = {"ollama_models": str(shared_ai_home / "models/ollama"),
                                  "embedding_cache": str(shared_ai_home / "cache/huggingface/hub")}
    (shared_ai_home / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    assert local_ai.setup_needed(models, project=tmp_path / "new-copy") is False
    weights = next((shared_ai_home / "cache/huggingface/hub").rglob("model.safetensors"))
    weights.unlink()
    assert local_ai.setup_needed(models, project=tmp_path / "new-copy") is True


@pytest.mark.parametrize("configured_path", ["data-local-ai", "nested/new-records"])
def test_readonly_setup_config_does_not_create_operational_data_directories(tmp_path, monkeypatch, configured_path):
    from frib_ds.config import Config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "app.yaml").write_text(json.dumps({"app": {"data_dir": configured_path}}), encoding="utf-8")
    monkeypatch.delenv("FRIB_DATA_DIR", raising=False)
    config = Config(config_dir, create_dirs=False)
    assert config.data_dir == tmp_path / configured_path
    assert config.event_dir == config.data_dir / "events"
    assert config.chroma_dir == config.data_dir / "chroma"
    assert not config.data_dir.exists()
    assert not config.document_dir.exists()
    assert not config.database_path.exists()


def test_readonly_setup_config_preserves_data_directory_override_without_creating_it(tmp_path, monkeypatch):
    from frib_ds.config import Config
    overridden = tmp_path / "override/records"
    monkeypatch.setenv("FRIB_DATA_DIR", str(overridden))
    config = Config(tmp_path / "config", create_dirs=False)
    assert config.data_dir == overridden
    assert not overridden.exists()
    assert not (tmp_path / "config").exists()


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def prohibited(*args, **kwargs):
        pytest.fail("Unit tests must not contact a server or execute downloaded software")
    monkeypatch.setattr(local_ai.LOCAL_HTTP, "open", prohibited)
    monkeypatch.setattr(local_ai, "urlopen", prohibited)
    monkeypatch.setattr(local_ai.subprocess, "Popen", prohibited)
    monkeypatch.setattr(local_ai.subprocess, "run", prohibited)


@pytest.fixture
def startup_stub(monkeypatch):
    from frib_ds import launcher
    stub = SimpleNamespace(guard_control_path=lambda path: path, ProjectLock=lambda path: nullcontext(), startup_progress=lambda *a: None,
                           atomic_json=lambda *args: pytest.fail("Unexpected model-validation receipt"))
    monkeypatch.setattr(launcher, "startup_module", lambda: stub)
    return stub


@pytest.mark.parametrize("llm,embedding", [("mock", "sentence_transformers"), ("ollama", "hash"),
                                         ("mock", "hash"), ("unknown", "sentence_transformers"), ("ollama", "unknown")])
def test_test_only_or_unknown_providers_are_rejected(models, llm, embedding):
    models["llm"]["provider"], models["embeddings"]["provider"] = llm, embedding
    with pytest.raises(RuntimeError, match="requires a real"):
        local_ai.validate_real_providers(models)


@pytest.mark.parametrize("llm", ["ollama", "lmstudio"])
def test_supported_real_providers_are_accepted(models, llm):
    models["llm"]["provider"] = llm
    assert local_ai.validate_real_providers(models) is None


def test_runtime_environment_uses_shared_paths_and_preserves_explicit_overrides(tmp_path, shared_ai_home):
    source = {"PATH": "/test/bin", "FRIB_AI_HOME": str(shared_ai_home)}
    env = local_ai.runtime_environment(tmp_path, source)
    assert env["HF_HOME"] == str(shared_ai_home / "cache/huggingface")
    assert env["FRIB_EMBEDDING_CACHE"] == str(shared_ai_home / "cache/huggingface/hub")
    assert env["OLLAMA_MODELS"] == str(shared_ai_home / "models/ollama")
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert source == {"PATH": "/test/bin", "FRIB_AI_HOME": str(shared_ai_home)}
    custom = {"FRIB_AI_HOME": str(shared_ai_home), "HF_HOME": "/existing/hf", "FRIB_EMBEDDING_CACHE": "/existing/embeddings", "OLLAMA_MODELS": "/existing/ollama", "HF_HUB_DISABLE_TELEMETRY": "custom"}
    assert all(local_ai.runtime_environment(tmp_path, custom)[key] == value for key, value in custom.items())
    assert local_ai.runtime_environment(tmp_path, {"HF_HOME": "/existing/hf"})["FRIB_EMBEDDING_CACHE"] == "/existing/hf/hub"
    assert not (tmp_path / ".frib").exists()
    assert not shared_ai_home.exists()


def test_shared_default_model_paths_are_identical_across_extracted_project_copies(tmp_path, shared_ai_home):
    source = {"FRIB_AI_HOME": str(shared_ai_home)}
    first = local_ai.runtime_environment(tmp_path / "FRIB_Final_Project 7", source)
    second = local_ai.runtime_environment(tmp_path / "FRIB_Final_Project 8", source)
    for key in ("FRIB_AI_HOME", "HF_HOME", "FRIB_EMBEDDING_CACHE", "OLLAMA_MODELS"):
        assert first[key] == second[key]
        assert str(shared_ai_home) in first[key]
    assert not shared_ai_home.exists()


def test_mac_default_shared_model_directory_is_outside_each_project_copy(tmp_path, monkeypatch):
    from frib_ds import ai_storage
    monkeypatch.delenv("FRIB_AI_HOME", raising=False)
    monkeypatch.setattr(ai_storage.platform, "system", lambda: "Darwin")
    expected = tmp_path / "user-home/Library/Application Support/FRIB"
    first = local_ai.runtime_environment(tmp_path / "project-copy-a", {})
    second = local_ai.runtime_environment(tmp_path / "project-copy-b", {})
    assert first["FRIB_AI_HOME"] == second["FRIB_AI_HOME"] == str(expected)
    assert first["OLLAMA_MODELS"] == second["OLLAMA_MODELS"] == str(expected / "models/ollama")
    assert first["FRIB_EMBEDDING_CACHE"] == second["FRIB_EMBEDDING_CACHE"] == str(expected / "cache/huggingface/hub")
    assert not expected.exists()


def test_complete_legacy_assets_are_reused_without_scanning_other_project_copies(tmp_path, shared_ai_home, real_ai_receipt, cached_semantic_model, cached_ollama_model):
    project = tmp_path / "existing-project"
    root = project / ".frib"
    cached_semantic_model(root / "cache/huggingface/hub")
    cached_ollama_model(root / "models/ollama")
    (root / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    env = local_ai.runtime_environment(project, {"FRIB_AI_HOME": str(shared_ai_home)})
    assert env["OLLAMA_MODELS"] == str(root / "models/ollama")
    assert env["FRIB_EMBEDDING_CACHE"] == str(root / "cache/huggingface/hub")
    other = local_ai.runtime_environment(tmp_path / "new-project", {"FRIB_AI_HOME": str(shared_ai_home)})
    assert other["OLLAMA_MODELS"] == str(shared_ai_home / "models/ollama")


def test_partial_legacy_assets_do_not_override_the_permanent_cache(tmp_path, shared_ai_home, real_ai_receipt, cached_semantic_model):
    root = tmp_path / ".frib"
    cached_semantic_model(root / "cache/huggingface/hub")
    (root / "models/ollama/manifests").mkdir(parents=True)
    (root / "real-ai-validation.json").write_text(json.dumps(real_ai_receipt), encoding="utf-8")
    env = local_ai.runtime_environment(tmp_path, {"FRIB_AI_HOME": str(shared_ai_home)})
    assert env["OLLAMA_MODELS"] == str(shared_ai_home / "models/ollama")
    assert env["FRIB_EMBEDDING_CACHE"] == str(shared_ai_home / "cache/huggingface/hub")


def test_configured_environment_restores_process_environment_on_failure(tmp_path, monkeypatch, shared_ai_home):
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("FRIB_EMBEDDING_CACHE", raising=False)
    monkeypatch.setenv("OLLAMA_MODELS", "/keep/models")
    import os
    with pytest.raises(RuntimeError, match="fixture failure"):
        with local_ai.configured_environment(tmp_path):
            assert os.environ["HF_HOME"] == str(shared_ai_home / "cache/huggingface")
            assert os.environ["OLLAMA_MODELS"] == "/keep/models"
            raise RuntimeError("fixture failure")
    assert "HF_HOME" not in os.environ and "FRIB_EMBEDDING_CACHE" not in os.environ
    assert os.environ["OLLAMA_MODELS"] == "/keep/models"


def test_temporary_download_permission_is_restored_after_repair(tmp_path, shared_ai_home):
    assert "HF_HUB_OFFLINE" not in os.environ
    with local_ai.configured_environment(tmp_path, source={"FRIB_AI_HOME": str(shared_ai_home)}) as env:
        env["HF_HUB_OFFLINE"] = "0"
        os.environ["HF_HUB_OFFLINE"] = "0"
    assert "HF_HUB_OFFLINE" not in os.environ


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434/", "http://[::1]:11434"])
def test_loopback_model_urls_are_accepted(url):
    assert local_ai._local_base_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", ["https://localhost:11434", "http://example.com:11434", "http://127.0.0.1.evil:11434",
                                "http://localhost:11434/api", "http://user:pass@localhost:11434", "http://localhost:11434/?target=remote",
                                "http://localhost:11434/#remote", "http://localhost:80", "http://localhost", "http://localhost:65536",
                                "http://localhost:invalid", "file:///private/models", "http://0.0.0.0:11434"])
def test_unsafe_model_urls_are_rejected_before_network(url):
    with pytest.raises(RuntimeError):
        local_ai._json_request(url, "/api/version")


def test_local_model_requests_disable_proxy_and_reject_redirects():
    proxy_handlers = [handler for handler in local_ai.LOCAL_HTTP.handlers if isinstance(handler, ProxyHandler)]
    # urllib drops a ProxyHandler with no configured proxies; neither form uses environment proxies.
    assert not proxy_handlers or all(handler.proxies == {} for handler in proxy_handlers)
    handler = next(handler for handler in local_ai.LOCAL_HTTP.handlers if isinstance(handler, local_ai._NoRedirects))
    request = Request("http://localhost:11434/api/version")
    with pytest.raises(HTTPError, match="cannot redirect"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://example.invalid/")


def test_json_request_only_uses_allowlisted_endpoints_and_object_responses(monkeypatch):
    calls = []
    class Response(io.BytesIO):
        pass
    def open_request(request, **kwargs):
        calls.append((request, kwargs))
        return Response(b'{"version":"fixture"}')
    monkeypatch.setattr(local_ai.LOCAL_HTTP, "open", open_request)
    assert local_ai._json_request("http://localhost:11434/", "/api/show", {"model": "qwen3:8b"}, timeout=4) == {"version": "fixture"}
    assert calls[0][0].full_url == "http://localhost:11434/api/show"
    assert json.loads(calls[0][0].data) == {"model": "qwen3:8b"}
    assert calls[0][1] == {"timeout": 4}
    with pytest.raises(ValueError, match="Unsupported"):
        local_ai._json_request("http://localhost:11434", "/api/delete")
    assert len(calls) == 1
    monkeypatch.setattr(local_ai.LOCAL_HTTP, "open", lambda *a, **k: Response(b"[]"))
    with pytest.raises(RuntimeError, match="invalid response"):
        local_ai._json_request("http://localhost:11434", "/api/version")


@pytest.mark.parametrize("relative", ["ollama", "Ollama.app/Contents/Resources/ollama"])
def test_private_runtime_discovery_without_path_entry(tmp_path, monkeypatch, relative):
    binary = tmp_path / ".frib/tools/ollama" / relative
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"unit test fixture")
    binary.chmod(0o755)
    monkeypatch.setattr(local_ai.shutil, "which", lambda *args: None)
    assert local_ai.ollama_binary(tmp_path, {}) == str(binary)


def test_shared_runtime_is_preferred_and_reused_from_each_project_copy(tmp_path, shared_ai_home, monkeypatch):
    binary = shared_ai_home / "tools/ollama/ollama"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"unit test fixture")
    binary.chmod(0o755)
    legacy = tmp_path / "project-a/.frib/tools/ollama/ollama"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy unit test fixture")
    legacy.chmod(0o755)
    monkeypatch.setattr(local_ai.shutil, "which", lambda *args: None)
    source = {"FRIB_AI_HOME": str(shared_ai_home)}
    assert local_ai.ollama_binary(tmp_path / "project-a", source) == str(binary)
    assert local_ai.ollama_binary(tmp_path / "project-b", source) == str(binary)


def test_explicit_runtime_path_has_precedence_and_invalid_explicit_path_does_not_fall_back(tmp_path, monkeypatch):
    binary = tmp_path / "chosen-ollama"
    binary.write_bytes(b"unit test fixture")
    binary.chmod(0o755)
    monkeypatch.setattr(local_ai.shutil, "which", lambda *args: pytest.fail("Explicit path must not use PATH"))
    assert local_ai.ollama_binary(tmp_path, {"FRIB_OLLAMA_BIN": str(binary)}) == str(binary)
    assert local_ai.ollama_binary(tmp_path, {"FRIB_OLLAMA_BIN": str(tmp_path / "missing")}) is None


def test_download_tls_context_requires_certificate_and_hostname_verification():
    context = local_ai.download_ssl_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.get_ca_certs()


def test_download_tls_context_adds_certifi_to_default_roots_and_preserves_explicit_root_store(monkeypatch):
    import certifi
    created, loaded = [], []
    context = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_REQUIRED,
                              load_verify_locations=lambda *a, **k: loaded.append((a, k)))
    def default_context(*args, **kwargs):
        created.append((args, kwargs, os.environ.get("SSL_CERT_FILE")))
        return context
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/organization-roots.pem")
    monkeypatch.setattr(ssl, "create_default_context", default_context)
    monkeypatch.setattr(certifi, "where", lambda: "/bundled/certifi-roots.pem")
    assert local_ai.download_ssl_context() is context
    assert len(created) == 1
    assert not {"cafile", "capath", "cadata"}.intersection(created[0][1])
    assert created[0][2] == "/custom/organization-roots.pem"
    assert os.environ["SSL_CERT_FILE"] == "/custom/organization-roots.pem"
    assert loaded in [
        [(("/bundled/certifi-roots.pem",), {})],
        [((), {"cafile": "/bundled/certifi-roots.pem"})],
    ]
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("verified_archive", [False, True])
def test_official_download_uses_verified_tls_without_bypassing_checksum_or_safe_extraction(tmp_path, shared_ai_home, monkeypatch, startup_stub, verified_archive):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as bundle:
        entry = tarfile.TarInfo("../../escape")
        entry.size = 1
        bundle.addfile(entry, io.BytesIO(b"x"))
    downloaded = payload.getvalue()
    context, calls = ssl.create_default_context(), []
    monkeypatch.setattr(local_ai, "download_ssl_context", lambda: context)
    monkeypatch.setattr(local_ai.platform, "system", lambda: "Darwin")
    def download(url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["context"].check_hostname is True
        assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
        return io.BytesIO(downloaded)
    monkeypatch.setattr(local_ai, "urlopen", download)
    if verified_archive:
        monkeypatch.setattr(local_ai, "OLLAMA_SHA256", hashlib.sha256(downloaded).hexdigest())
        expected_error = (tarfile.FilterError, RuntimeError)
    else:
        monkeypatch.setattr(local_ai, "OLLAMA_SHA256", "0" * 64)
        monkeypatch.setattr(local_ai.tarfile, "open", lambda *a, **k: pytest.fail("Do not extract before checksum verification"))
        expected_error = RuntimeError
    with pytest.raises(expected_error):
        local_ai.install_ollama(tmp_path)
    assert calls == [(local_ai.OLLAMA_URL, {"timeout": 60, "context": context})]
    assert not (tmp_path / ".frib/tools/ollama").exists()
    assert not (tmp_path / ".frib/tools/escape").exists()
    assert not (shared_ai_home / "tools/ollama").exists()
    assert not (shared_ai_home / "tools/escape").exists()


def test_checksum_mismatch_cannot_extract_or_execute_download(tmp_path, shared_ai_home, monkeypatch, startup_stub):
    archive = tmp_path / "untrusted.tgz"
    archive.write_bytes(b"not the expected trusted release")
    monkeypatch.setattr(local_ai.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_ai.tarfile, "open", lambda *a, **k: pytest.fail("Checksum must be verified before extraction"))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        local_ai.install_ollama(tmp_path, archive)
    assert not (tmp_path / ".frib/tools/ollama").exists()
    assert not (shared_ai_home / "tools/ollama").exists()


def test_checksum_verified_archive_cannot_traverse_outside_staging(tmp_path, shared_ai_home, monkeypatch, startup_stub):
    archive = tmp_path / "malicious.tgz"
    with tarfile.open(archive, "w:gz") as bundle:
        entry = tarfile.TarInfo("../../escape")
        entry.size = 1
        bundle.addfile(entry, io.BytesIO(b"x"))
    monkeypatch.setattr(local_ai.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_ai, "OLLAMA_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises((tarfile.FilterError, RuntimeError)):
        local_ai.install_ollama(tmp_path, archive)
    assert not (tmp_path / ".frib/tools/escape").exists()
    assert not (tmp_path / ".frib/tools/ollama").exists()
    assert not (shared_ai_home / "tools/escape").exists()
    assert not (shared_ai_home / "tools/ollama").exists()


def test_verified_runtime_installs_once_in_shared_storage_for_other_project_copies(tmp_path, shared_ai_home, monkeypatch, startup_stub):
    archive = tmp_path / "valid-fixture.tgz"
    contents = b"unit test executable fixture; never run"
    with tarfile.open(archive, "w:gz") as bundle:
        entry = tarfile.TarInfo("ollama")
        entry.size, entry.mode = len(contents), 0o644
        bundle.addfile(entry, io.BytesIO(contents))
    monkeypatch.setattr(local_ai.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_ai, "OLLAMA_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    executions = []
    def version_probe(arguments, **kwargs):
        executions.append(arguments)
        return subprocess.CompletedProcess(arguments, 0)
    monkeypatch.setattr(local_ai.subprocess, "run", version_probe)
    monkeypatch.setattr(local_ai.shutil, "which", lambda *args: None)
    binary = local_ai.install_ollama(tmp_path / "first-project-copy", archive_path=archive)
    assert binary == str(shared_ai_home / "tools/ollama/ollama")
    assert Path(binary).read_bytes() == contents
    assert len(executions) == 1 and executions[0][1:] == ["--version"]
    assert local_ai.ollama_binary(tmp_path / "second-project-copy") == binary
    assert not (tmp_path / "first-project-copy/.frib/tools/ollama").exists()


class Process:
    def __init__(self, *, exited=False, terminate_timeout=False):
        self.exited, self.terminate_timeout = exited, terminate_timeout
        self.actions = []
    def poll(self):
        return 0 if self.exited else None
    def terminate(self):
        self.actions.append("terminate")
    def kill(self):
        self.actions.append("kill")
    def wait(self, timeout):
        self.actions.append(("wait", timeout))
        if self.terminate_timeout and timeout == 10:
            raise subprocess.TimeoutExpired("fixture", timeout)
        self.exited = True
        return 0


def test_existing_ollama_server_is_never_claimed_or_stopped(models, tmp_path, monkeypatch):
    monkeypatch.setattr(local_ai, "_json_request", lambda *a, **k: {"version": "fixture"})
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *a, **k: pytest.fail("Do not locate or start another server"))
    runtime = local_ai.ensure_ollama(models, tmp_path, {})
    assert runtime.process is None
    runtime.close()
    runtime.close()
    assert not (tmp_path / ".frib").exists()


@pytest.mark.parametrize("base_url,expected_host", [("http://localhost:11434", "127.0.0.1:11434"),
                                                    ("http://127.0.0.1:22444", "127.0.0.1:22444"),
                                                    ("http://[::1]:11434", "[::1]:11434")])
def test_owned_ollama_server_is_started_with_shared_model_store_and_closed(models, tmp_path, shared_ai_home, monkeypatch, startup_stub, base_url, expected_host):
    models["llm"]["ollama_base_url"] = base_url
    calls, spawns = [], []
    def request(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise URLError("No existing server")
        return {"version": "fixture"}
    process = Process()
    monkeypatch.setattr(local_ai, "_json_request", request)
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *args: "/private/ollama")
    monkeypatch.setattr(local_ai.subprocess, "Popen", lambda *a, **k: spawns.append((a, k)) or process)
    runtime = local_ai.ensure_ollama(models, tmp_path, {"FRIB_AI_HOME": str(shared_ai_home)})
    assert runtime.process is process and not runtime.output.closed
    arguments, kwargs = spawns[0]
    assert arguments == (["/private/ollama", "serve"],)
    assert kwargs["env"]["OLLAMA_HOST"] == expected_host
    assert kwargs["env"]["OLLAMA_MODELS"] == str(shared_ai_home / "models/ollama")
    assert kwargs["env"]["OLLAMA_NO_CLOUD"] == "1"
    runtime.close()
    assert runtime.output.closed
    assert process.actions == ["terminate", ("wait", 10)]


def test_owned_server_is_closed_on_startup_failure(models, tmp_path, monkeypatch, startup_stub):
    monkeypatch.setattr(local_ai, "_json_request", lambda *a, **k: (_ for _ in ()).throw(URLError("offline")))
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *args: "/private/ollama")
    process = Process(exited=True)
    monkeypatch.setattr(local_ai.subprocess, "Popen", lambda *a, **k: process)
    with pytest.raises(RuntimeError, match="stopped during startup"):
        local_ai.ensure_ollama(models, tmp_path, {})
    assert process.actions == []
    assert (tmp_path / ".frib/ollama.log").is_file()


def test_unidentified_existing_service_is_rejected_without_starting_or_stopping_it(models, tmp_path, monkeypatch):
    monkeypatch.setattr(local_ai, "_json_request", lambda *a, **k: {"unrelated": "service"})
    with pytest.raises(RuntimeError, match="not an identifiable Ollama"):
        local_ai.ensure_ollama(models, tmp_path, {})
    assert not (tmp_path / ".frib").exists()


def test_owned_service_with_invalid_readiness_metadata_is_stopped(models, tmp_path, monkeypatch, startup_stub):
    calls, outputs = [], []
    def request(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise URLError("No existing server")
        return {"unrelated": "service"}
    process = Process()
    monkeypatch.setattr(local_ai, "_json_request", request)
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *args: "/private/ollama")
    monkeypatch.setattr(local_ai.subprocess, "Popen", lambda *a, **k: outputs.append(k["stdout"]) or process)
    with pytest.raises(RuntimeError, match="did not identify its Ollama version"):
        local_ai.ensure_ollama(models, tmp_path, {})
    assert process.actions == ["terminate", ("wait", 10)]
    assert outputs[0].closed


def test_owned_process_that_ignores_termination_is_killed_and_log_closed():
    process, output = Process(terminate_timeout=True), io.StringIO()
    runtime = local_ai.OllamaRuntime(process, output)
    runtime.close()
    assert process.actions == ["terminate", ("wait", 10), "kill", ("wait", 5)]
    assert output.closed


def test_missing_runtime_is_reported_without_install_or_test_provider_fallback(models, tmp_path, monkeypatch):
    monkeypatch.setattr(local_ai, "_json_request", lambda *a, **k: (_ for _ in ()).throw(URLError("offline")))
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *args: None)
    monkeypatch.setattr(local_ai, "install_ollama", lambda *args: pytest.fail("No installation was requested"))
    with pytest.raises(RuntimeError, match="Ollama is missing"):
        local_ai.ensure_ollama(models, tmp_path, {}, install=False)
    assert models["llm"]["provider"] == "ollama" and models["embeddings"]["provider"] == "sentence_transformers"


def test_missing_real_model_is_an_actionable_error_without_fallback(models, monkeypatch):
    calls = []
    def request(base, endpoint, *args, **kwargs):
        calls.append(endpoint)
        raise HTTPError(base + endpoint, 404, "model missing", {}, None)
    monkeypatch.setattr(local_ai, "_json_request", request)
    with pytest.raises(RuntimeError, match="No mock AI was substituted"):
        local_ai.check_ollama_model(models, generate=True)
    assert calls == ["/api/show"]
    assert models["llm"]["provider"] == "ollama"


def test_real_model_generation_is_verified_and_empty_answer_rejected(models, monkeypatch):
    calls = []
    answer = {"message": {"content": "READY"}}
    def request(base, endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload))
        return {"model_info": {}} if endpoint == "/api/show" else answer
    monkeypatch.setattr(local_ai, "_json_request", request)
    result = local_ai.check_ollama_model(models, generate=True)
    assert result["generation_verified"] is True and result["sample"] == "READY"
    assert calls[-1][1]["model"] == "qwen3:8b" and calls[-1][1]["stream"] is False
    answer["message"]["content"] = "   "
    with pytest.raises(RuntimeError, match="returned no answer"):
        local_ai.check_ollama_model(models, generate=True)


@pytest.mark.parametrize("vectors,error", [([], "shape"), ([[], [], []], "shape"),
                                          ([[1, 0], [1], [0, 1]], "shape"),
                                          ([[1, 0], [float("nan"), 0], [0, 1]], "finite"),
                                          ([[1, 0], [0, 1], [1, 0]], "semantic similarity")])
def test_invalid_or_semantically_wrong_embedding_vectors_are_rejected(models, monkeypatch, vectors, error):
    from frib_ds.rag import embeddings
    monkeypatch.setattr(embeddings, "build_embedding_provider", lambda config: SimpleNamespace(embed=lambda texts: vectors))
    with pytest.raises(RuntimeError, match=error):
        local_ai.check_embedding(models)


def test_embedding_semantic_probe_reports_real_dimensions_and_relatedness(models, monkeypatch):
    from frib_ds.rag import embeddings
    inputs = []
    def factory(config):
        assert config == models["embeddings"]
        def embed(texts):
            inputs.extend(texts)
            return [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]
        return SimpleNamespace(embed=embed)
    monkeypatch.setattr(embeddings, "build_embedding_provider", factory)
    report = local_ai.check_embedding(models)
    assert report["provider"] == "sentence_transformers" and report["dimensions"] == 2
    assert report["similarity_related"] > report["similarity_unrelated"]
    assert len(inputs) == 3


def test_setup_missing_model_fails_without_embedding_fallback_or_validation_receipt(models, tmp_path, monkeypatch, startup_stub, capsys):
    from frib_ds import config
    monkeypatch.setattr(local_ai, "PROJECT", tmp_path)
    monkeypatch.setattr(config, "Config", lambda **kwargs: SimpleNamespace(models=models))
    @contextmanager
    def environment(**kwargs):
        yield {}
    monkeypatch.setattr(local_ai, "configured_environment", environment)
    runtime = local_ai.OllamaRuntime(output=io.StringIO())
    monkeypatch.setattr(local_ai, "ensure_ollama", lambda *a, **k: runtime)
    monkeypatch.setattr(local_ai, "check_ollama_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Required real model is missing")))
    monkeypatch.setattr(local_ai, "check_embedding", lambda *a, **k: pytest.fail("Do not continue setup after failed generation"))
    assert local_ai.main([]) == 1
    assert runtime.output.closed
    assert "Required real model is missing" in capsys.readouterr().err
    assert not (tmp_path / ".frib/real-ai-validation.json").exists()


def test_install_prepares_private_cli_when_existing_server_has_no_available_cli(models, tmp_path, shared_ai_home, monkeypatch, startup_stub):
    from frib_ds import config
    monkeypatch.setattr(local_ai, "PROJECT", tmp_path)
    config_calls, installs, pulls, released, receipts = [], [], [], [], []
    def configuration(**kwargs):
        config_calls.append(kwargs)
        return SimpleNamespace(models=models, config_dir=tmp_path / "config")
    monkeypatch.setattr(config, "Config", configuration)
    env = local_ai.runtime_environment(tmp_path)
    @contextmanager
    def environment(**kwargs):
        assert kwargs == {"downloads": False}
        yield env
    monkeypatch.setattr(local_ai, "configured_environment", environment)
    existing_server = local_ai.OllamaRuntime()
    def ensure(selected, **kwargs):
        assert selected is models and kwargs == {"env": env, "install": True}
        return existing_server
    monkeypatch.setattr(local_ai, "ensure_ollama", ensure)
    monkeypatch.setattr(local_ai, "ollama_binary", lambda **kwargs: None)
    private_binary = str(shared_ai_home / "tools/ollama/ollama")
    def install(project, **kwargs):
        assert kwargs == {"env": env}
        installs.append(project)
        (tmp_path / ".frib").mkdir(exist_ok=True)
        return private_binary
    monkeypatch.setattr(local_ai, "install_ollama", install)
    def pull(arguments, **kwargs):
        pulls.append((arguments, kwargs))
        assert not kwargs["stdout"].closed
        return subprocess.CompletedProcess(arguments, 0)
    monkeypatch.setattr(local_ai.subprocess, "run", pull)
    def release(process):
        assert process is None, "Setup must not claim or stop another application's Ollama server"
        released.append(process)
    monkeypatch.setattr(local_ai, "_stop_owned", release)
    def model_check(selected, generate=False):
        assert selected is models
        if not generate:
            raise RuntimeError("Required model weights are missing")
        return {"provider": "ollama", "model": "qwen3:8b", "generation_verified": True}
    monkeypatch.setattr(local_ai, "check_ollama_model", model_check)
    monkeypatch.setattr(local_ai, "check_embedding", lambda selected: {"provider": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimensions": 384})
    monkeypatch.setattr(local_ai.importlib.metadata, "version", lambda name: "unit-test-version")
    def write_receipt(path, payload):
        receipts.append((path, payload))
        path.write_text(json.dumps(payload), encoding="utf-8")
    startup_stub.atomic_json = write_receipt
    assert local_ai.main(["--install"]) == 0
    assert config_calls == [{"create_dirs": False}]
    assert installs == [tmp_path]
    assert len(pulls) == 1 and pulls[0][0] == [private_binary, "pull", "qwen3:8b"]
    assert pulls[0][1]["env"]["OLLAMA_HOST"] == models["llm"]["ollama_base_url"]
    assert pulls[0][1]["check"] is True
    assert existing_server.process is None and released == [None]
    receipt_path = tmp_path / ".frib/real-ai-validation.json"
    assert len(receipts) == 1 and receipts[0][0] == receipt_path
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["llm"]["generation_verified"] is True
    assert receipt["embedding"]["dimensions"] == 384
    assert receipt["mock_ai"] is False and receipt["hash_embeddings"] is False
    assert not (tmp_path / "data").exists() and not (tmp_path / "data-local-ai").exists()


def test_install_reuses_available_shared_model_without_downloading_or_pulling(models, tmp_path, shared_ai_home, cached_semantic_model, monkeypatch, startup_stub):
    from frib_ds import config
    monkeypatch.setattr(local_ai, "PROJECT", tmp_path / "new-project-copy")
    cached_semantic_model(shared_ai_home / "cache/huggingface/hub")
    monkeypatch.setattr(config, "Config", lambda **kwargs: SimpleNamespace(models=models, config_dir=tmp_path / "config"))
    env = local_ai.runtime_environment(tmp_path / "new-project-copy")
    @contextmanager
    def environment(**kwargs):
        assert kwargs == {"downloads": False}
        yield env
    monkeypatch.setattr(local_ai, "configured_environment", environment)
    existing_server, checked = local_ai.OllamaRuntime(), []
    monkeypatch.setattr(local_ai, "ensure_ollama", lambda *a, **k: existing_server)
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *a, **k: str(shared_ai_home / "tools/ollama/ollama"))
    monkeypatch.setattr(local_ai, "install_ollama", lambda *a, **k: pytest.fail("An available model must not trigger runtime download"))
    def check_model(selected, generate=False):
        assert selected is models
        checked.append(generate)
        return {"provider": "ollama", "model": "qwen3:8b", "generation_verified": generate}
    monkeypatch.setattr(local_ai, "check_ollama_model", check_model)
    monkeypatch.setattr(local_ai, "check_embedding", lambda selected: {"provider": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimensions": 384})
    monkeypatch.setattr(local_ai.importlib.metadata, "version", lambda name: "unit-test-version")
    def local_receipt(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    startup_stub.atomic_json = local_receipt
    assert local_ai.main(["--install"]) == 0
    assert checked == [False, True]
    assert existing_server.process is None
    receipt = json.loads((shared_ai_home / "real-ai-validation.json").read_text(encoding="utf-8"))
    assert receipt["llm"]["provider"] == "ollama"
    assert receipt["embedding"]["model"] == "all-MiniLM-L6-v2"
    assert receipt["mock_ai"] is False and receipt["hash_embeddings"] is False
    assert local_ai.setup_needed(models, project=tmp_path / "another-project-copy") is False
    assert not (tmp_path / "new-project-copy/data").exists()
    assert not (tmp_path / "new-project-copy/data-local-ai").exists()


def test_existing_server_cannot_trigger_duplicate_pull_of_complete_local_model(models, tmp_path, shared_ai_home, cached_ollama_model, monkeypatch, startup_stub, capsys):
    from frib_ds import config
    monkeypatch.setattr(local_ai, "PROJECT", tmp_path)
    cached_ollama_model(shared_ai_home / "models/ollama")
    monkeypatch.setattr(config, "Config", lambda **kwargs: SimpleNamespace(models=models, config_dir=tmp_path / "config"))
    env = local_ai.runtime_environment(tmp_path)
    @contextmanager
    def environment(**kwargs):
        yield env
    monkeypatch.setattr(local_ai, "configured_environment", environment)
    runtime = local_ai.OllamaRuntime()
    monkeypatch.setattr(local_ai, "ensure_ollama", lambda *a, **k: runtime)
    monkeypatch.setattr(local_ai, "check_ollama_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Server uses a different model store")))
    monkeypatch.setattr(local_ai, "ollama_binary", lambda *a, **k: pytest.fail("Do not start a pull for model weights already on disk"))
    monkeypatch.setattr(local_ai, "install_ollama", lambda *a, **k: pytest.fail("Do not install another runtime before resolving the store mismatch"))
    assert local_ai.main(["--install"]) == 1
    assert "no duplicate download was started" in capsys.readouterr().err
    assert runtime.process is None
    assert local_ai.ollama_cache_available(models, env) is True
