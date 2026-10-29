"""Run the local API and dashboard together, with readiness checks and cleanup."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser


PROJECT = Path(__file__).resolve().parents[2]


def startup_module():
    spec = importlib.util.spec_from_file_location("frib_startup_checks", PROJECT / "start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def available_port(port: int) -> bool:
    with socket.socket() as sock:
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


def main():
    parser = argparse.ArgumentParser(description="Start FRIB locally with a single command.")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8501, help="Dashboard port")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check installation without starting services")
    parser.add_argument("--local-ai", action="store_true", help="Use configured Ollama model and semantic embeddings (requires rag extra)")
    args = parser.parse_args()
    if any(not 1024 <= p <= 65535 for p in (args.api_port, args.port)) or args.api_port == args.port:
        parser.error("Choose two different ports between 1024 and 65535")
    startup = startup_module()
    checked = startup.check_environment(sys.executable, PROJECT)
    if not checked["ok"]:
        print("Application setup needs repair: " + "; ".join(checked["issues"]))
        print("Run Start FRIB.cmd to prepare a validated private environment.")
        return 1
    if args.check:
        print(f"FRIB installation is ready. Project: {PROJECT}")
        return 0
    service_lock = startup.ProjectLock(PROJECT / ".frib/services.lock")
    if not service_lock.acquire():
        print("FRIB is already running or an environment replacement is in progress. Stop the earlier FRIB window with Ctrl+C before restarting.")
        return 1
    if not available_port(args.api_port) or not available_port(args.port):
        service_lock.close()
        print(f"Port {args.api_port} or {args.port} is already in use. Close the earlier FRIB window or choose --api-port and --port.")
        return 1
    env = os.environ.copy()
    env.setdefault("FRIB_CONFIG_DIR", str(PROJECT / "config"))
    if args.local_ai:
        env.update(FRIB_LLM_PROVIDER="ollama", FRIB_EMBEDDING_PROVIDER="sentence_transformers")
        env.setdefault("FRIB_VECTOR_PROVIDER", "sqlite")
        # Keep incompatible demo/semantic vectors and demo procedures separate.
        env.setdefault("FRIB_DATA_DIR", str(PROJECT / "data-local-ai"))
    env["FRIB_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    logs = Path(env.get("FRIB_DATA_DIR", str(PROJECT / "data"))) / "logs"
    processes = []
    handles = []
    try:
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
            wait_ready(health_url, process, timeout=180 if args.local_ai else 60)
        url = f"http://127.0.0.1:{args.port}"
        print(f"FRIB is ready: {url}\nKeep this window open. Press Ctrl+C to stop both services.\nLogs: {logs}", flush=True)
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
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
        service_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
