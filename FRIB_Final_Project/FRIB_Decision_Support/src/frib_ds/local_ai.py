"""Install and verify the real local models; never select test providers."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen

from frib_ds.ai_storage import AIStorageLock, ai_home, atomic_json as shared_atomic_json, ensure_directory, guard_path


PROJECT = Path(__file__).resolve().parents[2]
OLLAMA_VERSION = "0.40.13"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-darwin.tgz"
OLLAMA_SHA256 = "bae29252232b9e1358cf5801a7d65a07442af18fb5467cb68c7fc3711f59c511"


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Local model requests cannot redirect", headers, fp)


LOCAL_HTTP = build_opener(ProxyHandler({}), _NoRedirects())


def download_ssl_context():
    """Keep TLS verification and add packaged roots for python.org macOS builds.

    Some Python installations lack a populated default OpenSSL CA file even
    though HTTPS clients such as Requests have certifi installed. Add that
    maintained bundle alongside default/custom system trust, never disable TLS.
    """
    import certifi
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def _read_receipt(path, shared=False, env=None):
    try:
        if shared:
            path = guard_path(path, env)
        elif path.is_symlink() or path.parent.is_symlink():
            return None
        if path.stat().st_size > 100_000:
            return None
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(receipt, dict) and receipt.get("mock_ai") is False and receipt.get("hash_embeddings") is False:
            return receipt
    except (OSError, ValueError, TypeError):
        pass
    return None


def runtime_environment(project=PROJECT, source=None):
    """Reuse durable per-user models across every downloaded project copy."""
    env = dict(os.environ if source is None else source)
    root = ai_home(env)
    env.setdefault("FRIB_AI_HOME", str(root))
    legacy = Path(project) / ".frib"
    shared_receipt = _read_receipt(root / "real-ai-validation.json", shared=True, env=env)
    legacy_receipt = _read_receipt(legacy / "real-ai-validation.json")
    # Retain a complete current-copy installation until explicitly moved to
    # shared storage. Never scan other folders or remove old project assets.
    legacy_complete = (not shared_receipt and legacy_receipt is not None
                       and isinstance(legacy_receipt.get("embedding"), dict)
                       and isinstance(legacy_receipt.get("llm"), dict)
                       and embedding_cache_available({"embeddings": legacy_receipt["embedding"]},
                                                     {"FRIB_EMBEDDING_CACHE": str(legacy / "cache/huggingface/hub")})
                       and ollama_cache_available({"llm": legacy_receipt["llm"]},
                                                  {"OLLAMA_MODELS": str(legacy / "models/ollama")}))
    cache_root = legacy if legacy_complete else root
    env.setdefault("HF_HOME", str(cache_root / "cache/huggingface"))
    env.setdefault("FRIB_EMBEDDING_CACHE", str(Path(env["HF_HOME"]) / "hub"))
    env.setdefault("OLLAMA_MODELS", str(cache_root / "models/ollama"))
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # A successfully prepared installation can load cached weights without
    # repeated network checks on every app start. Explicit setup permits new
    # downloads again; user overrides are respected.
    if (shared_receipt is not None or legacy_receipt is not None) and "HF_HUB_OFFLINE" not in env:
        env["HF_HUB_OFFLINE"] = "1"
        env["FRIB_HF_OFFLINE_DEFAULTED"] = "1"
    return env


def validate_real_providers(models):
    llm = models.get("llm", {}).get("provider", "ollama")
    embedding = models.get("embeddings", {}).get("provider", "sentence_transformers")
    if llm not in {"ollama", "lmstudio"} or embedding != "sentence_transformers":
        raise RuntimeError(
            "FRIB requires a real Ollama or LM Studio model and SentenceTransformers embeddings. "
            "Mock AI and hash embeddings are test-only and cannot start the application. "
            "Remove old FRIB_LLM_PROVIDER/FRIB_EMBEDDING_PROVIDER overrides and run SETUP_LOCAL_AI.command."
        )


def embedding_cache_available(models, env):
    model = models.get("embeddings", {}).get("model", "all-MiniLM-L6-v2")
    if not isinstance(model, str) or not model.strip():
        return False
    local = Path(model).expanduser()
    if local.is_dir():
        candidates = [local]
    else:
        identifier = model if "/" in model else "sentence-transformers/" + model
        snapshots = Path(env["FRIB_EMBEDDING_CACHE"]) / ("models--" + identifier.replace("/", "--")) / "snapshots"
        candidates = list(snapshots.iterdir()) if snapshots.is_dir() else []
    for snapshot in candidates:
        if not (snapshot / "modules.json").is_file():
            continue
        directories = [snapshot, *[path for path in snapshot.iterdir() if path.is_dir()]]
        if any((path / "config.json").is_file() and any((path / weights).is_file() for weights in ("model.safetensors", "pytorch_model.bin")) for path in directories):
            return True
    return False


def setup_needed(models, project=PROJECT):
    """A matching successful setup can skip downloads and repeated generation."""
    env = runtime_environment(project)
    receipts = [_read_receipt(ai_home(env) / "real-ai-validation.json", shared=True, env=env),
                _read_receipt(Path(project) / ".frib/real-ai-validation.json")]
    for receipt in receipts:
        try:
            if receipt is None:
                continue
            matched = all(isinstance(receipt.get(recorded), dict)
                          and all(receipt[recorded].get(key) == models[configured].get(key) for key in ("provider", "model"))
                          for configured, recorded in (("llm", "llm"), ("embeddings", "embedding")))
            storage = receipt.get("storage")
            if storage is not None:
                matched = matched and isinstance(storage, dict) and storage.get("ollama_models") == env["OLLAMA_MODELS"] and storage.get("embedding_cache") == env["FRIB_EMBEDDING_CACHE"]
            matched = matched and embedding_cache_available(models, env)
            if matched:
                return False
        except (KeyError, TypeError):
            continue
    return True


def _local_base_url(base_url):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise RuntimeError("Automatic Ollama setup requires an HTTP loopback URL without credentials or a path.")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise RuntimeError("Invalid Ollama port") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("Ollama must use an unprivileged local port.")
    return base_url.rstrip("/")


def _json_request(base_url, endpoint, payload=None, timeout=5):
    base_url = _local_base_url(base_url)
    if endpoint not in {"/api/version", "/api/show", "/api/chat"}:
        raise ValueError("Unsupported local model endpoint")
    request = Request(base_url + endpoint, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with LOCAL_HTTP.open(request, timeout=timeout) as response:
        data = json.loads(response.read(2_000_000))
    if not isinstance(data, dict):
        raise RuntimeError("The local AI server returned an invalid response.")
    return data


def ollama_binary(project=PROJECT, env=None):
    env = os.environ if env is None else env
    explicit = env.get("FRIB_OLLAMA_BIN")
    candidates = [explicit] if explicit else [
        str(guard_path(ai_home(env) / "tools/ollama/ollama", env)),
        str(Path(project) / ".frib/tools/ollama/ollama"), shutil.which("ollama"),
        str(Path(project) / ".frib/tools/ollama/Ollama.app/Contents/Resources/ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).absolute())
    return None


def ollama_cache_available(models, env):
    """Recognize complete local model assets without reading multi-GB blobs."""
    name = models.get("llm", {}).get("model", "qwen3:8b")
    if not isinstance(name, str) or not name.strip():
        return False
    parts = name.split("/")
    last, separator, tag = parts[-1].rpartition(":")
    if separator:
        parts[-1] = last
    else:
        tag = "latest"
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", part) for part in (*parts, tag)):
        return False
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library", *parts]
    elif len(parts) == 2:
        parts = ["registry.ollama.ai", *parts]
    root = Path(env["OLLAMA_MODELS"])
    manifest = root.joinpath("manifests", *parts, tag)
    try:
        if manifest.stat().st_size > 1_000_000:
            return False
        details = json.loads(manifest.read_text(encoding="utf-8"))
        layers = [details["config"], *details["layers"]]
        for layer in layers:
            digest = layer["digest"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                return False
            blob = root / "blobs" / digest.replace(":", "-")
            if not blob.is_file() or blob.stat().st_size != layer["size"]:
                return False
        return bool(layers)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def install_ollama(project=PROJECT, archive_path=None, env=None):
    with AIStorageLock(env):
        return _install_ollama(project, archive_path, env)


def _install_ollama(project=PROJECT, archive_path=None, env=None):
    """Use the official release and verify its published SHA-256 before extraction."""
    if platform.system() != "Darwin":
        raise RuntimeError("Install Ollama from https://ollama.com/download for this OS, then rerun setup.")
    destination = guard_path(ai_home(env) / "tools/ollama", env)
    ensure_directory(destination.parent, env)
    if destination.exists():
        binary = destination / "ollama"
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(guard_path(binary, env))
        raise RuntimeError("The shared Ollama directory already exists but is unusable; retain it for inspection before retrying.")
    with tempfile.TemporaryDirectory(prefix="ollama-install-", dir=destination.parent) as scratch:
        archive = Path(archive_path) if archive_path else Path(scratch) / "ollama.tgz"
        if not archive_path:
            print(f"Downloading official Ollama {OLLAMA_VERSION}...", flush=True)
            with urlopen(OLLAMA_URL, timeout=60, context=download_ssl_context()) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        with archive.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest != OLLAMA_SHA256:
            raise RuntimeError("Ollama download checksum mismatch; no downloaded executable was installed.")
        staged = Path(scratch) / "runtime"
        staged.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(staged, filter="data")
        binary = staged / "ollama"
        if not binary.is_file() or binary.is_symlink():
            raise RuntimeError("The Ollama release did not contain its expected executable.")
        binary.chmod(binary.stat().st_mode | 0o111)
        subprocess.run([str(binary), "--version"], capture_output=True, check=True, timeout=15)
        (staged / "FRIB_INSTALL_RECEIPT.json").write_text(json.dumps({"version": OLLAMA_VERSION, "source": OLLAMA_URL, "sha256": digest}, indent=2) + "\n")
        guard_path(destination, env)
        staged.rename(destination)
    return str(destination / "ollama")


def _stop_owned(process):
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class OllamaRuntime:
    """Own only a server we start; leave existing user servers running."""
    def __init__(self, process=None, output=None):
        self.process, self.output = process, output

    def close(self):
        try:
            _stop_owned(self.process)
        finally:
            if self.output is not None:
                self.output.close()


def ensure_ollama(models, project=PROJECT, env=None, install=False):
    env = runtime_environment(project, env)
    base_url = _local_base_url(models["llm"].get("ollama_base_url", "http://localhost:11434"))
    try:
        info = _json_request(base_url, "/api/version")
        if not isinstance(info.get("version"), str):
            raise RuntimeError("The service on the Ollama port is not an identifiable Ollama server.")
        return OllamaRuntime()
    except (OSError, ValueError):
        pass
    binary = ollama_binary(project, env)
    if binary is None:
        if not install:
            raise RuntimeError("Ollama is missing. Run SETUP_LOCAL_AI.command to install the real AI models.")
        binary = install_ollama(project, env=env)
    parsed = urlsplit(base_url)
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    env["OLLAMA_HOST"] = f"{host}:{parsed.port}"
    env.setdefault("OLLAMA_NO_CLOUD", "1")
    models_path = Path(env["OLLAMA_MODELS"])
    if models_path.is_relative_to(ai_home(env)):
        ensure_directory(models_path, env)
    else:
        models_path.mkdir(parents=True, exist_ok=True)
    from frib_ds.launcher import startup_module
    startup = startup_module()
    logs = startup.guard_control_path(Path(project) / ".frib/ollama.log")
    logs.parent.mkdir(parents=True, exist_ok=True)
    output = logs.open("a", encoding="utf-8")
    runtime = OllamaRuntime(output=output)
    try:
        runtime.process = subprocess.Popen([binary, "serve"], env=env, stdout=output, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if runtime.process.poll() is not None:
                raise RuntimeError(f"Ollama stopped during startup. See {logs}")
            try:
                info = _json_request(base_url, "/api/version", timeout=2)
                if not isinstance(info.get("version"), str):
                    raise RuntimeError("The local model service did not identify its Ollama version.")
                return runtime
            except (OSError, ValueError):
                time.sleep(0.25)
        raise RuntimeError(f"Ollama did not become ready. See {logs}")
    except BaseException:
        runtime.close()
        raise


def check_ollama_model(models, generate=False):
    llm = models["llm"]
    model = llm.get("model", "qwen3:8b")
    base_url = llm.get("ollama_base_url", "http://localhost:11434")
    try:
        details = _json_request(base_url, "/api/show", {"model": model})
        if "model_info" not in details:
            raise RuntimeError("Ollama did not return model metadata.")
        if generate:
            result = _json_request(base_url, "/api/chat", {"model": model, "messages": [{"role": "user", "content": "Reply only with READY."}], "think": False, "stream": False, "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 16}}, timeout=int(llm.get("timeout_seconds", 300)))
            answer = result.get("message", {}).get("content", "").strip()
            if not answer:
                raise RuntimeError("The real language model returned no answer.")
            return {"provider": "ollama", "model": model, "generation_verified": True, "sample": answer}
        return {"provider": "ollama", "model": model, "model_available": True}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Ollama model {model!r} is unavailable. Run SETUP_LOCAL_AI.command. No mock AI was substituted.") from exc


def check_embedding(models):
    from frib_ds.rag.embeddings import build_embedding_provider
    provider = build_embedding_provider(models["embeddings"])
    vectors = provider.embed(["A leaking pipe releases water.", "Water escapes from a damaged pipe.", "The telescope observes a distant galaxy."])
    if len(vectors) != 3 or not vectors[0] or any(len(v) != len(vectors[0]) or not all(math.isfinite(x) for x in v) for v in vectors):
        raise RuntimeError("The real embedding model failed its vector shape/finite-value check.")
    scores = [sum(a*b for a, b in zip(vectors[0], vector)) for vector in vectors[1:]]
    if scores[0] <= scores[1]:
        raise RuntimeError("The embedding model failed the semantic similarity check.")
    return {"provider": "sentence_transformers", "model": models["embeddings"]["model"], "dimensions": len(vectors[0]), "similarity_related": scores[0], "similarity_unrelated": scores[1]}


@contextmanager
def configured_environment(project=PROJECT, downloads=False, source=None):
    env = runtime_environment(project, source)
    explicit = os.environ if source is None else source
    if downloads and ("HF_HUB_OFFLINE" not in explicit or env.get("FRIB_HF_OFFLINE_DEFAULTED") == "1"):
        env["HF_HUB_OFFLINE"] = "0"
    keys = {key: os.environ.get(key) for key in env if os.environ.get(key) != env[key]}
    # Setup may enable a first/missing embedding download after checking the
    # actual cache. Restore this switch even when it was initially absent.
    keys.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE"))
    try:
        os.environ.update(env)
        yield env
    finally:
        for key, previous in keys.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args(arguments)
    from frib_ds.config import Config
    from frib_ds.launcher import startup_module
    runtime = None
    try:
        with configured_environment(downloads=False) as env:
            config = Config(create_dirs=False)
            validate_real_providers(config.models)
            if config.models["llm"]["provider"] != "ollama":
                from frib_ds.ai_settings import selection_from_models, probe_model
                selection = selection_from_models(config.models)
                probe = probe_model(selection)
                embedding = check_embedding(config.models)
                receipt = {'llm': {'provider': selection.provider, 'model': selection.model, 'generation_verified': True, 'sample': probe['sample']},
                           'embedding': embedding, 'mock_ai': False, 'hash_embeddings': False,
                           'storage': {'ollama_models': env['OLLAMA_MODELS'], 'embedding_cache': env['FRIB_EMBEDDING_CACHE']}}
                shared_atomic_json(ai_home(env) / 'real-ai-validation.json', receipt, env)
                print(json.dumps(receipt, indent=2), flush=True)
                return 0
            with AIStorageLock(env), startup_module().ProjectLock(PROJECT / ".frib/model-setup.lock"):
                runtime = ensure_ollama(config.models, env=env, install=args.install)
                if args.install:
                    try:
                        check_ollama_model(config.models, generate=False)
                        model_available = True
                    except RuntimeError:
                        model_available = False
                    if model_available:
                        if not ollama_binary(env=env):
                            install_ollama(PROJECT, env=env)
                        print(f"Reusing installed {config.models['llm']['model']} model weights; no download needed.", flush=True)
                    else:
                        if ollama_cache_available(config.models, env):
                            raise RuntimeError(
                                "This Ollama server cannot see the complete model already stored on this Mac. "
                                "Close the other Ollama application/server, or configure an unused local OLLAMA_BASE_URL port, "
                                "then start FRIB again. Existing model weights were retained and no duplicate download was started."
                            )
                        binary = ollama_binary(env=env)
                        if not binary:
                            binary = install_ollama(PROJECT, env=env)
                        pull_env = dict(env, OLLAMA_HOST=config.models["llm"].get("ollama_base_url", "http://localhost:11434"))
                        if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
                            startup_module().startup_progress("ai", "Downloading the missing language model into permanent FRIB storage. First launch may download about 5.2 GB; keep this window open.")
                        print(f"Downloading missing {config.models['llm']['model']} model weights (about 5.2 GB for Qwen3 8B)...", flush=True)
                        with (PROJECT / ".frib/model-install.log").open("a") as output:
                            subprocess.run([binary, "pull", config.models["llm"]["model"]], env=pull_env, stdout=output, stderr=subprocess.STDOUT, check=True)
                print("Verifying real language-model generation...", flush=True)
                llm = check_ollama_model(config.models, generate=True)
                print("Loading/verifying semantic embedding model...", flush=True)
                if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
                    startup_module().startup_progress("ai", "Loading and checking the semantic search model for your procedures.")
                if args.install and not embedding_cache_available(config.models, env):
                    if "HF_HUB_OFFLINE" not in os.environ or env.get("FRIB_HF_OFFLINE_DEFAULTED") == "1":
                        env["HF_HUB_OFFLINE"] = "0"
                        os.environ["HF_HUB_OFFLINE"] = "0"
                embedding = check_embedding(config.models)
                source, destination = PROJECT / "data", PROJECT / "data-local-ai"
                if args.install and (source / "frib.db").is_file() and not os.path.lexists(destination):
                    from frib_ds.migrate_semantic import migrate_semantic
                    print("Copying saved records and rebuilding their index with real semantic embeddings...", flush=True)
                    if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
                        startup_module().startup_progress("ai", "Loading your saved records and preparing their semantic search index.")
                    migrate_semantic(source, destination, config.config_dir)
                receipt = {"llm": llm, "embedding": embedding, "dependencies": {name: importlib.metadata.version(name) for name in ("sentence-transformers", "torch", "transformers")}, "mock_ai": False, "hash_embeddings": False,
                           "storage": {"ollama_models": env["OLLAMA_MODELS"], "embedding_cache": env["FRIB_EMBEDDING_CACHE"]}}
                shared_atomic_json(ai_home(env) / "real-ai-validation.json", receipt, env)
                startup_module().atomic_json(PROJECT / ".frib/real-ai-validation.json", receipt)
                print(json.dumps(receipt, indent=2), flush=True)
                print("Real local AI and semantic embeddings are ready. Start FRIB normally.", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Real AI setup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
