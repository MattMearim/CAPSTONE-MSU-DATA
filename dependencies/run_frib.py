"""Start/stop this project's private local workspace without global installations."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener, Request
import webbrowser
import requests
from urllib.parse import urlsplit

DEPENDENCIES = Path(__file__).resolve().parent
WORKSPACE = DEPENDENCIES.parent
PROJECT = WORKSPACE / 'FRIB_Final_Project' / 'FRIB_Decision_Support'
PYTHON = DEPENDENCIES / 'venv' / 'Scripts' / 'python.exe'
RUNTIME = DEPENDENCIES / 'runtime'
LOGS = DEPENDENCIES / 'logs'
STATUS = RUNTIME / 'workspace.json'
STOP = RUNTIME / 'stop-request.json'
HTTP = build_opener(ProxyHandler({}))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        for attempt in range(12):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 11:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    try:
        if path.stat().st_size > 100_000:
            return None
        result = json.loads(path.read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else None
    except (OSError, ValueError):
        return None


def process_identity(pid):
    if os.name != 'nt' or type(pid) is not int or pid <= 0:
        return None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
        size = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return None
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            return None
        return {'pid': pid, 'executable': name.value, 'creation_time_filetime': (created.dwHighDateTime << 32) | created.dwLowDateTime}
    finally:
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(handle)


def same_process(identity):
    return (isinstance(identity, dict) and process_identity(identity.get('pid')) ==
            {key: identity.get(key) for key in ('pid', 'executable', 'creation_time_filetime')})


def request(path, payload=None, timeout=3):
    url = 'http://127.0.0.1:' + path
    req = Request(url, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with HTTP.open(req, timeout=timeout) as response:
        content = response.read(1_000_000)
        return json.loads(content) if response.headers.get_content_type() == 'application/json' else content.decode('utf-8')


def healthy(state):
    try:
        return (state and state.get('status') == 'ready' and same_process(state.get('supervisor'))
                and request('8000/health').get('instance_id') == state['instance_id']
                and request('8501/_stcore/health').strip() == 'ok')
    except (OSError, ValueError, TypeError, KeyError):
        return False


def environment():
    env = dict(os.environ)
    ai = DEPENDENCIES / 'ai'
    env.update(FRIB_AI_HOME=str(ai), HF_HOME=str(ai / 'cache/huggingface'),
               FRIB_EMBEDDING_CACHE=str(ai / 'cache/huggingface/hub'),
               OLLAMA_MODELS=str(ai / 'models/ollama'), OLLAMA_HOST='127.0.0.1:11434', OLLAMA_NO_CLOUD='1',
               FRIB_DEPENDENCIES_DIR=str(DEPENDENCIES), FRIB_BUNDLED_OLLAMA_URL='http://127.0.0.1:11434',
               FRIB_OLLAMA_BIN=str(DEPENDENCIES / 'ollama/ollama.exe'),
               FRIB_CONFIG_DIR=str(PROJECT / 'config'), FRIB_DATA_DIR=str(PROJECT / 'data-local-ai'),
               FRIB_API_URL='http://127.0.0.1:8000',
               FRIB_EMBEDDING_PROVIDER='sentence_transformers', FRIB_EMBEDDING_MODEL='all-MiniLM-L6-v2',
               FRIB_VECTOR_PROVIDER='sqlite', HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_OFFLINE='1',
               PYTHONUTF8='1', PYTHONUNBUFFERED='1', PIP_CACHE_DIR=str(DEPENDENCIES / 'cache/pip'),
               TEMP=str(DEPENDENCIES / 'temp'), TMP=str(DEPENDENCIES / 'temp'),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    # The private environment's editable installation points at this source copy.
    env['PATH'] = str(PYTHON.parent) + os.pathsep + str(DEPENDENCIES / 'ollama') + os.pathsep + env.get('PATH', '')
    return env


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def selected_ai():
    from frib_ds.config import Config
    from frib_ds.ai_settings import selection_from_models
    return selection_from_models(Config(PROJECT / 'config', create_dirs=False).models)


def start_bundled_ollama():
    """Start only the bundled server on its fixed local port; preserve foreign listeners."""
    from frib_ds.ai_settings import _json_get
    env = environment()
    url = env['FRIB_BUNDLED_OLLAMA_URL']
    installed = read_json(DEPENDENCIES / 'ollama-server.json')
    try:
        info = _json_get(url + '/api/version')
        if not isinstance(info.get('version'), str):
            raise RuntimeError('The bundled model port is occupied by another service.')
        if installed and same_process(installed) and installed.get('server_url') == url:
            return {**installed, 'managed': True}
        raise RuntimeError('Another Ollama server occupies port 11434. It was left running; use its own model manager or stop it before starting the bundled server.')
    except requests.ConnectionError:
        pass
    if not free_port(11434):
        raise RuntimeError('Port 11434 is occupied. The unrelated service was left running.')
    LOGS.mkdir(parents=True, exist_ok=True)
    binary = DEPENDENCIES / 'ollama/ollama.exe'
    with (LOGS / 'ollama.log').open('a', encoding='utf-8') as output:
        child = subprocess.Popen([str(binary), 'serve'], cwd=DEPENDENCIES, env=env, stdout=output,
                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    identity = process_identity(child.pid)
    if identity is None:
        raise RuntimeError('Could not record portable model-server ownership.')
    record = {**identity, 'models_directory': env['OLLAMA_MODELS'], 'server_url': url,
              'owner': 'FRIB private workspace', 'installed_locally': True}
    atomic_json(DEPENDENCIES / 'ollama-server.json', record)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('The portable model server stopped. See dependencies/logs/ollama.log.')
        try:
            info = _json_get(url + '/api/version')
            if isinstance(info.get('version'), str):
                return {**record, 'managed': True}
        except requests.RequestException:
            time.sleep(0.5)
    raise RuntimeError('The portable model server did not become ready. Its process was retained for inspection.')


def stop_owned(identity):
    if not same_process(identity):
        return
    taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
    # Windows virtual-environment launchers can have a second interpreter child.
    # /T stops only the tree rooted at the exact process identity we started.
    subprocess.run([str(taskkill), '/PID', str(identity['pid']), '/T', '/F'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)


def serve():
    import msvcrt
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    lock = (RUNTIME / 'supervisor.lock').open('a+b')
    lock.seek(0, 2)
    if not lock.tell():
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return 1
    state = {'schema_version': '1.0', 'status': 'starting', 'instance_id': uuid.uuid4().hex,
             'supervisor': process_identity(os.getpid()), 'project': str(PROJECT),
             'data_dir': str(PROJECT / 'data-local-ai'), 'url': 'http://127.0.0.1:8501', 'services': {}}
    children, outputs = [], []
    external_owned_ollama = None
    atomic_json(STATUS, state)
    env = environment()
    selection = selected_ai()
    env['FRIB_INSTANCE_ID'] = state['instance_id']

    def launch(name, command):
        output = (LOGS / (name + '.log')).open('a', encoding='utf-8')
        outputs.append(output)
        child = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        children.append(child)
        identity = process_identity(child.pid)
        if identity is None:
            raise RuntimeError('Could not record the owned ' + name + ' process.')
        state['services'][name] = identity
        atomic_json(STATUS, state)
        return child

    def wait(endpoint, child=None, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            stop = read_json(STOP)
            if stop and stop.get('instance_id') == state['instance_id']:
                raise KeyboardInterrupt
            if child is not None and child.poll() is not None:
                raise RuntimeError('A service exited; see ' + str(LOGS))
            try:
                return request(endpoint)
            except (OSError, ValueError):
                time.sleep(0.4)
        raise RuntimeError('Timed out waiting for ' + endpoint + '; see ' + str(LOGS))

    try:
        if not PYTHON.is_file():
            raise RuntimeError('Private Python environment is missing: ' + str(PYTHON))
        if not free_port(8000) or not free_port(8501):
            raise RuntimeError('Port 8000 or 8501 belongs to another process; it was left alone.')
        receipt = read_json(DEPENDENCIES / 'ai/real-ai-validation.json')
        if not receipt or receipt.get('mock_ai') is not False or receipt.get('hash_embeddings') is not False:
            raise RuntimeError('Real model setup has not completed. See dependencies/README.md.')
        if selection.provider == 'ollama' and selection.base_url == env['FRIB_BUNDLED_OLLAMA_URL']:
            try:
                record = start_bundled_ollama()
                state['services']['ollama'] = {key: record[key] for key in ('pid', 'executable', 'creation_time_filetime')}
                env['FRIB_MANAGED_OLLAMA_URL'] = record['server_url']
                atomic_json(STATUS, state)
            except Exception as exc:
                state['ai_warning'] = str(exc)
        # An offline chat server must not prevent opening AI Settings to choose a working model.
        backend = launch('backend', [str(PYTHON), '-m', 'uvicorn', 'frib_ds.api.main:app', '--host', '127.0.0.1', '--port', '8000'])
        result = wait('8000/health', backend)
        if (result.get('instance_id') != state['instance_id'] or result.get('llm_provider') != selection.provider
                or result.get('embedding_provider') != 'sentence_transformers'):
            raise RuntimeError('The API did not report the expected real providers and workspace identity.')
        dashboard = launch('dashboard', [str(PYTHON), '-m', 'streamlit', 'run', str(PROJECT / 'src/frib_ds/dashboard/app.py'),
                                        '--server.address=127.0.0.1', '--server.port=8501', '--server.headless=true',
                                        '--browser.gatherUsageStats=false'])
        wait('8501/_stcore/health', dashboard)
        state.update(status='ready', providers={'llm': selection.provider + '/' + selection.model, 'embeddings': 'sentence_transformers/all-MiniLM-L6-v2', 'vectors': 'sqlite'})
        atomic_json(STATUS, state)
        print('FRIB is ready: ' + state['url'], flush=True)
        next_ai_refresh = 0
        while True:
            stop = read_json(STOP)
            if stop and stop.get('instance_id') == state['instance_id']:
                break
            if any(child.poll() is not None for child in children):
                raise RuntimeError('An owned service stopped; see ' + str(LOGS))
            # A user can start the bundled server from AI Settings after initially choosing LM Studio.
            installed = read_json(DEPENDENCIES / 'ollama-server.json')
            if installed and same_process(installed) and Path(installed['executable']).resolve() == (DEPENDENCIES / 'ollama/ollama.exe').resolve():
                state['services']['ollama'] = {key: installed[key] for key in ('pid', 'executable', 'creation_time_filetime')}
            if time.monotonic() >= next_ai_refresh:
                next_ai_refresh = time.monotonic() + 5
                try:
                    active = request('8000/health', timeout=2)
                    name = active['llm_provider'] + '/' + active.get('llm_model', '')
                    if state['providers']['llm'] != name:
                        state['providers']['llm'] = name
                        atomic_json(STATUS, state)
                except (OSError, ValueError, KeyError):
                    pass
            time.sleep(0.5)
        state['status'] = 'stopped'
        return 0
    except KeyboardInterrupt:
        state['status'] = 'stopped'
        return 0
    except Exception as exc:
        state.update(status='failed', error=str(exc))
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    finally:
        for name in ('dashboard', 'backend', 'ollama'):
            identity = state['services'].get(name)
            if identity is not None:
                try:
                    stop_owned(identity)
                except (OSError, subprocess.SubprocessError):
                    pass
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        for output in outputs:
            output.close()
        atomic_json(STATUS, state)
        stop = read_json(STOP)
        if stop and stop.get('instance_id') == state['instance_id']:
            STOP.unlink(missing_ok=True)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status', 'serve'))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.action == 'serve':
        return serve()
    state = read_json(STATUS)
    if args.action == 'status':
        print(json.dumps({**(state or {'status': 'not_started'}), 'healthy': bool(healthy(state))}, indent=2))
        return 0 if healthy(state) else 1
    if args.action == 'stop':
        if not state or not same_process(state.get('supervisor')):
            print('This private FRIB workspace is not running.')
            return 0
        atomic_json(STOP, {'instance_id': state['instance_id']})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            current = read_json(STATUS)
            if not same_process(state['supervisor']) or (current and current.get('status') in {'stopped', 'failed'}):
                print('FRIB workspace stopped.')
                return 0
            time.sleep(0.5)
        print('Stop is still pending; inspect ' + str(LOGS), file=sys.stderr)
        return 1
    if healthy(state):
        print('FRIB is already ready: http://127.0.0.1:8501')
        if not args.no_browser:
            webbrowser.open('http://127.0.0.1:8501')
        return 0
    if state and same_process(state.get('supervisor')):
        print('FRIB startup is already in progress. See ' + str(LOGS))
        return 0
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / 'supervisor.log').open('a', encoding='utf-8') as output:
        child = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), 'serve'], cwd=WORKSPACE,
                                 env=environment(), stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        state = read_json(STATUS)
        if healthy(state):
            print('FRIB is ready: http://127.0.0.1:8501')
            if not args.no_browser:
                webbrowser.open('http://127.0.0.1:8501')
            return 0
        if child.poll() is not None:
            print((state or {}).get('error', 'Startup stopped. See ' + str(LOGS)), file=sys.stderr)
            return 1
        time.sleep(0.5)
    print('Startup is still running; inspect ' + str(LOGS), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
