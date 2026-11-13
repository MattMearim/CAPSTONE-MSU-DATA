"""Run the local API and dashboard together, with readiness checks and cleanup."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import uuid
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser


PROJECT = Path(__file__).resolve().parents[2]


class _NoHealthRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A loopback service check must never contact a redirected destination.
        raise HTTPError(req.full_url, code, "Service health checks must not redirect.", headers, fp)


_HEALTH_OPENER = build_opener(ProxyHandler({}), _NoHealthRedirects())


def urlopen(url, timeout=2):
    """Read only the two fixed health endpoints, directly over loopback."""
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.port is None or not 1024 <= parsed.port <= 65535
            or parsed.path not in {"/health", "/_stcore/health"}):
        raise ValueError("Service health checks must use a fixed loopback health endpoint.")
    return _HEALTH_OPENER.open(url, timeout=timeout)


def startup_module():
    spec = importlib.util.spec_from_file_location("frib_startup_checks", PROJECT / "start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def available_port(port: int) -> bool:
    with socket.socket() as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_ready(url, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A service stopped during startup. See the log files in data/logs.")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Startup timed out waiting for {url}. See data/logs for details.")


def requested_data_dir(args):
    # Semantic vectors must never reuse the legacy hash-index workspace.
    default = PROJECT / "data-local-ai"
    return Path(os.environ.get("FRIB_DATA_DIR", str(default))).resolve()


def running_app_url(startup, args):
    """Reopen only this project's healthy instance in the requested workspace."""
    try:
        path = startup.guard_control_path(PROJECT / ".frib/running-services.json")
        if path.stat().st_size > 10_000:
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != "1.0":
            return None
        if state.get("project") != str(PROJECT.resolve()) or state.get("data_dir") != str(requested_data_dir(args)):
            return None
        if state.get("local_ai") is not bool(args.local_ai):
            return None
        if any(type(state.get(key)) is not int or not 1024 <= state[key] <= 65535 for key in ("api_port", "port")):
            return None
        if (state["api_port"] == state["port"] or args.api_port == args.port
                or any(type(getattr(args, key)) is not int or not 1024 <= getattr(args, key) <= 65535
                       for key in ("api_port", "port"))):
            return None
        # A normal one-click start can reopen the safe ports selected for this
        # workspace earlier. An explicit port request must still match exactly.
        # Callers without the new flags retain the original strict contract.
        if any(getattr(args, key + "_explicit", True) and state[key] != getattr(args, key)
               for key in ("api_port", "port")):
            return None
        token = state.get("instance_id")
        if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
            return None
        with urlopen(f"http://127.0.0.1:{state['api_port']}/health", timeout=2) as response:
            health = json.loads(response.read(65_536))
            if response.status != 200 or not isinstance(health, dict) or health.get("status") != "ok" or health.get("instance_id") != token:
                return None
        url = f"http://127.0.0.1:{state['port']}"
        with urlopen(url + "/_stcore/health", timeout=2) as response:
            if response.status != 200:
                return None
        return url
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def parse_launcher_args(arguments=None):
    """Parse supported launch options while retaining explicit port intent."""
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    parser = argparse.ArgumentParser(description="Start FRIB locally with a single command.", allow_abbrev=False)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8501, help="Dashboard port")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Verify installed dependencies and both real AI models")
    parser.add_argument("--local-ai", action="store_true", help="Explicitly select Ollama and SentenceTransformers (real AI is the default)")
    args = parser.parse_args(arguments)
    args.api_port_explicit = any(value == "--api-port" or value.startswith("--api-port=") for value in arguments)
    args.port_explicit = any(value == "--port" or value.startswith("--port=") for value in arguments)
    if any(not 1024 <= p <= 65535 for p in (args.api_port, args.port)) or args.api_port == args.port:
        parser.error("Choose two different ports between 1024 and 65535")
    return args


def reopen_running_app(startup, args):
    """Authenticate and reopen a matching workspace without taking ownership."""
    url = running_app_url(startup, args)
    if not url:
        return False
    if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
        startup.startup_progress("ready", "Your existing workspace is ready. Its original startup window controls shutdown.", url=url, owned=False)
    print(f"FRIB is already open: {url}\nReusing the running app. Its original launcher window controls shutdown.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    return True


def main(arguments=None):
    args = parse_launcher_args(arguments)
    startup = startup_module()
    # An already-ready workspace does not need environment repair, downloads,
    # package checks or ownership of a second launcher. This also handles a
    # healthy older service pair whose launcher no longer holds its OS lock.
    if not args.check and reopen_running_app(startup, args):
        return 0
    checked = startup.check_environment(sys.executable, PROJECT)
    if not checked["ok"]:
        print("Application setup needs repair: " + "; ".join(checked["issues"]))
        print("Run Start FRIB.command on macOS or Start FRIB.cmd on Windows to prepare a validated private environment.")
        return 1
    if args.check:
        from frib_ds.local_ai import main as check_models
        return check_models([])
    service_lock = startup.ProjectLock(PROJECT / ".frib/services.lock")
    if not service_lock.acquire():
        # Startup may have completed between the first health check and lock.
        if reopen_running_app(startup, args):
            return 0
        print("FRIB is starting, preparing an environment, or running with different workspace settings. Wait for startup, or stop its original launcher window with Ctrl+C. This window has not started another copy.")
        return 1
    if not available_port(args.api_port) or not available_port(args.port):
        service_lock.close()
        print(f"Port {args.api_port} or {args.port} is already in use. Close the earlier FRIB window or choose --api-port and --port.")
        return 1
    from frib_ds.local_ai import runtime_environment, configured_environment, validate_real_providers, ensure_ollama, check_ollama_model, setup_needed, main as setup_models
    env = runtime_environment(PROJECT)
    env.setdefault("FRIB_CONFIG_DIR", str(PROJECT / "config"))
    if args.local_ai:
        # Local AI means a real selected provider; it must not overwrite a saved LM Studio profile.
        env.setdefault("FRIB_VECTOR_PROVIDER", "sqlite")
    env.setdefault("FRIB_DATA_DIR", str(requested_data_dir(args)))
    env["FRIB_INSTANCE_ID"] = uuid.uuid4().hex
    env["FRIB_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    logs = Path(env.get("FRIB_DATA_DIR", str(PROJECT / "data"))) / "logs"
    processes = []
    handles = []
    signals = startup.ShutdownSignals()
    signals.install()
    model_runtime = None
    try:
        if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
            startup.startup_progress("ai", "Checking the real AI and semantic search installed on this Mac.")
        # Validate the actual child configuration before opening a dashboard.
        # Explicit test providers remain available to isolated tests, never to
        # the user-facing launchers.
        from frib_ds.config import Config
        with configured_environment(PROJECT, source=env):
            models = Config(create_dirs=False).models
        validate_real_providers(models)
        if models["llm"]["provider"] == "ollama":
            def prepare_models():
                print("Checking installed AI files. Only missing models will be downloaded; keep this window open...", flush=True)
                with configured_environment(PROJECT, source=env):
                    if setup_models(["--install"]) != 0:
                        raise RuntimeError("Automatic AI setup could not finish. Check the setup message above, then start FRIB again.")
                env.update(runtime_environment(PROJECT, env))

            prepared = setup_needed(models, PROJECT)
            if prepared:
                prepare_models()
            else:
                print(f"Reusing the real AI installed on this Mac. Model storage: {env['OLLAMA_MODELS']}", flush=True)
                if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
                    startup.startup_progress("ai", "Using the real AI models already installed on this Mac. No model download is needed.")
            model_runtime = ensure_ollama(models, PROJECT, env)
            try:
                check_ollama_model(models)
            except RuntimeError:
                if prepared:
                    raise
                model_runtime.close()
                model_runtime = None
                prepare_models()
                model_runtime = ensure_ollama(models, PROJECT, env)
                check_ollama_model(models)
        if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
            startup.startup_progress("workspace", "Starting your workspace and checking that its services are ready.")
        logs.mkdir(parents=True, exist_ok=True)
        commands = [
            ("backend", [startup.win_path(sys.executable), "-m", "uvicorn", "frib_ds.api.main:app", "--host", "127.0.0.1", "--port", str(args.api_port)], f"{env['FRIB_API_URL']}/health"),
            ("dashboard", [startup.win_path(sys.executable), "-m", "streamlit", "run", startup.win_path(PROJECT / "src/frib_ds/dashboard/app.py"), "--server.address=127.0.0.1", f"--server.port={args.port}", "--server.headless=true", "--browser.gatherUsageStats=false"], f"http://127.0.0.1:{args.port}/_stcore/health"),
        ]
        for name, command, health_url in commands:
            output = (logs / f"{name}.log").open("a", encoding="utf-8")
            handles.append(output)
            print(f"Starting {name}...", flush=True)
            process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=output, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(health_url, process, timeout=180)
        url = f"http://127.0.0.1:{args.port}"
        startup.atomic_json(PROJECT / ".frib/running-services.json", {
            "schema_version": "1.0", "project": str(PROJECT.resolve()),
            "api_port": args.api_port, "port": args.port, "data_dir": str(requested_data_dir(args)),
            "local_ai": bool(args.local_ai), "instance_id": env["FRIB_INSTANCE_ID"], "pid": os.getpid(),
        })
        print(f"FRIB is ready: {url}\nReal AI: {models['llm']['provider']} / {models['llm']['model']}\nSemantic embeddings: {models['embeddings']['model']}\nKeep this window open. Press Ctrl+C to stop both services.\nLogs: {logs}", flush=True)
        if os.environ.get("FRIB_STARTUP_WINDOW") == "1":
            startup.startup_progress("ready", "Your workspace is ready. Keep this window open; use Stop workspace when you finish.", url=url, owned=True)
        if not args.no_browser:
            webbrowser.open(url)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("A service stopped. Check data/logs, then restart FRIB.")
    except KeyboardInterrupt:
        print("\nStopping FRIB...", flush=True)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"FRIB could not continue: {exc}", flush=True)
        return 1
    finally:
        signals.ignore_during_cleanup()
        try:
            for process in reversed(processes):
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass  # A child can finish between poll() and terminate().
            for process in processes:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for handle in handles:
                handle.close()
            if model_runtime is not None:
                model_runtime.close()
            try:
                startup.guard_control_path(PROJECT / ".frib/running-services.json").unlink(missing_ok=True)
            except (OSError, RuntimeError) as exc:
                print(f"Could not clear the last startup receipt: {exc}", flush=True)
        finally:
            service_lock.close()
            signals.close()


if __name__ == "__main__":
    raise SystemExit(main())
