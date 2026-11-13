"""Local chat-provider selection, verified application and bounded model downloads.

Embeddings are deliberately outside this settings contract: changing chat models
must not change the document index's embedding fingerprint.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
import requests

DEFAULT_URLS = {'ollama': 'http://127.0.0.1:11434', 'lmstudio': 'http://127.0.0.1:1234/v1'}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def local_url(value: str, provider: str) -> str:
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.port is None
                or not 1024 <= parsed.port <= 65535
                or parsed.path not in ({'', '/v1'} if provider == 'lmstudio' else {''})):
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError('Use an HTTP localhost address with a port; LM Studio may end in /v1. Credentials and other paths are not allowed.') from exc
    if provider == 'lmstudio' and not parsed.path:
        value += '/v1'
    host = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
    return f'http://{host}:{parsed.port}' + ('/v1' if provider == 'lmstudio' else '')


class ModelServer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['ollama', 'lmstudio']
    base_url: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def valid_server(self):
        self.base_url = local_url(self.base_url, self.provider)
        return self


class AISelection(ModelServer):
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.0, ge=0, le=2, allow_inf_nan=False)
    timeout_seconds: int = Field(default=300, ge=15, le=600)
    context_length: int = Field(default=4096, ge=512, le=32768)
    max_output_tokens: int = Field(default=500, ge=64, le=8192)

    @field_validator('model')
    @classmethod
    def model_identifier(cls, value):
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError('Enter the model identifier shown by your model server.')
        return value

    @model_validator(mode='after')
    def token_budget(self):
        if self.max_output_tokens >= self.context_length:
            raise ValueError('Maximum answer tokens must be smaller than the context window.')
        return self

    def llm_config(self) -> dict:
        return {**self.model_dump(exclude={'base_url'}),
                'ollama_base_url': self.base_url if self.provider == 'ollama' else DEFAULT_URLS['ollama'],
                'lmstudio_base_url': self.base_url if self.provider == 'lmstudio' else DEFAULT_URLS['lmstudio']}


class ApplySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selection: AISelection
    profile_name: str = Field(min_length=1, max_length=80)
    test_token: str = Field(min_length=1, max_length=64)

    @field_validator('profile_name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError('Enter a name for this saved profile.')
        return value


class AutomaticSetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['balanced', 'speed', 'capacity'] = 'balanced'
    model: str | None = Field(default=None, max_length=200)
    auto_adjust: bool = Field(default=True, strict=True)


class InstalledModelSwitch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selection: AISelection


def selection_from_models(models: dict) -> AISelection:
    llm = models.get('llm', {})
    provider = llm.get('provider', 'ollama')
    if provider not in DEFAULT_URLS:
        raise ValueError('AI settings are available for real Ollama and LM Studio providers.')
    return AISelection(provider=provider, model=llm.get('model', 'qwen3:8b'),
                       base_url=llm.get(provider + '_base_url', DEFAULT_URLS[provider]),
                       **{key: llm[key] for key in ('temperature', 'timeout_seconds', 'context_length', 'max_output_tokens') if key in llm})


def preferences_dir(config_dir) -> Path:
    override = os.getenv('FRIB_AI_PROFILE_ROOT')
    if override:
        key = hashlib.sha256(str(Path(config_dir).resolve()).encode()).hexdigest()[:16]
        return Path(override) / key
    return Path(config_dir)


def settings_path(config_dir) -> Path:
    return preferences_dir(config_dir) / 'ai-settings.json'


def _guard(path: Path):
    for part in (path, path.parent):
        if part.exists() or part.is_symlink():
            stat = part.lstat()
            if part.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400 or (part.is_file() and stat.st_nlink != 1):
                raise ValueError('AI settings must use an ordinary, unlinked configuration file.')


def read_profiles(config_dir) -> dict:
    path = settings_path(config_dir)
    _guard(path)
    if not path.exists():
        return {'schema_version': '1.0', 'active_profile': None, 'profiles': [], 'automation': {'enabled': False, 'mode': 'balanced'}}
    if path.stat().st_size > 128_000:
        raise ValueError('The AI settings file is too large.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema_version') != '1.0'
            or not isinstance(data.get('profiles'), list) or len(data['profiles']) > 20):
        raise ValueError('The saved AI profiles are invalid.')
    names = []
    profiles = []
    for entry in data['profiles']:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip() or len(entry['name']) > 80:
            raise ValueError('A saved AI profile has an invalid name.')
        names.append(entry['name'])
        profiles.append({'name': entry['name'], 'selection': AISelection.model_validate(entry.get('selection')).model_dump(),
                         'verified_at': entry.get('verified_at'), 'capabilities': entry.get('capabilities', {})})
    if len(names) != len(set(names)) or (data.get('active_profile') is not None and data['active_profile'] not in names):
        raise ValueError('The saved active AI profile does not exist or has a duplicate name.')
    policy = data.get('automation', {'enabled': False, 'mode': 'balanced'})
    if (not isinstance(policy, dict) or type(policy.get('enabled')) is not bool
            or policy.get('mode') not in {'balanced', 'speed', 'capacity'}):
        raise ValueError('The saved automatic AI preference is invalid.')
    return {'schema_version': '1.0', 'active_profile': data.get('active_profile'), 'profiles': profiles, 'automation': policy}


def saved_llm_config(config_dir) -> dict:
    data = read_profiles(config_dir)
    for profile in data['profiles']:
        if profile['name'] == data['active_profile']:
            return AISelection.model_validate(profile['selection']).llm_config()
    return {}


def _write_profiles(config_dir, data):
    _write_json_file(settings_path(config_dir), data)


def _write_json_file(path, data):
    _guard(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        _guard(path)
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _session():
    session = requests.Session()
    session.trust_env = False
    return session


def _json_get(url, *, timeout=(3, 15)):
    with _session() as session, session.get(url, timeout=timeout, stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f'Model server returned HTTP {response.status_code}. Check its address and start its local API server.')
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('Model server response exceeded the size limit.')
        return json.loads(body)


def start_bundled_server():
    """Optional private-launcher integration; no executable path comes from a request."""
    import importlib.util
    root = os.getenv('FRIB_DEPENDENCIES_DIR')
    if not root:
        raise ValueError('Start the project with START_PROJECT.cmd to use the bundled model server.')
    path = Path(root).resolve() / 'run_frib.py'
    if not path.is_file() or path.is_symlink():
        raise ValueError('The private workspace launcher is unavailable.')
    spec = importlib.util.spec_from_file_location('frib_private_model_control', path)
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    result = control.start_bundled_ollama()
    os.environ['FRIB_MANAGED_OLLAMA_URL'] = result['server_url']
    return {'started': True, 'base_url': result['server_url']}


def list_models(server: ModelServer, *, timeout=(3, 15)) -> list[dict]:
    payload = _json_get(server.base_url + ('/api/tags' if server.provider == 'ollama' else '/models'), timeout=timeout)
    if not isinstance(payload, dict):
        raise ValueError('The server did not return a model list.')
    entries = payload.get('models' if server.provider == 'ollama' else 'data')
    if not isinstance(entries, list):
        raise ValueError('The server did not return a compatible model list.')
    result = []
    for item in entries[:1000]:
        if not isinstance(item, dict):
            continue
        name = item.get('name') or item.get('id')
        if isinstance(name, str) and name.strip() and len(name) <= 200:
            result.append({'id': name, 'size_bytes': item.get('size') if isinstance(item.get('size'), int) else None,
                           'digest': item.get('digest') if isinstance(item.get('digest'), str) else None,
                           'parameter_size': (item.get('details') or {}).get('parameter_size') if isinstance(item.get('details', {}), dict) else None})
    return sorted({entry['id']: entry for entry in result}.values(), key=lambda entry: entry['id'])


def probe_model(selection: AISelection) -> dict:
    from frib_ds.rag.llm import build_llm_provider
    provider = build_llm_provider(selection.llm_config())
    answer = provider.chat([{'role': 'user', 'content': 'Reply briefly with READY.'}])
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('The model returned an empty answer.')
    schema = {'type': 'object', 'properties': {'ready': {'type': 'boolean'}}, 'required': ['ready'], 'additionalProperties': False}
    structured = provider.chat([{'role': 'user', 'content': 'Return exactly {"ready": true}, using the required JSON schema.'}], json_schema=schema)
    try:
        parsed = json.loads(structured)
    except (ValueError, TypeError) as exc:
        raise ValueError('Chat worked, but the model did not return the structured JSON required for review drafts.') from exc
    if parsed != {'ready': True}:
        raise ValueError('The model did not pass the structured JSON check required for review drafts.')
    return {'chat': True, 'structured_json': True, 'sample': answer.strip()[:300]}


class AISettingsManager:
    def __init__(self, config_dir):
        self.config_dir = Path(config_dir)
        self._lock = threading.RLock()
        self._tests = {}
        self._jobs = {}
        self._probe_slot = threading.BoundedSemaphore(1)
        self._hardware_cache = None
        self._setup_cancel = threading.Event()
        self._watching = False
        self._setup = {'status': 'idle', 'stage': 'idle'}
        progress_file = preferences_dir(self.config_dir) / 'ai-setup-job.json'
        try:
            _guard(progress_file)
            if progress_file.is_file() and progress_file.stat().st_size < 64000:
                previous = json.loads(progress_file.read_text(encoding='utf-8'))
                if isinstance(previous, dict) and previous.get('status') in {'running', 'completed', 'failed', 'cancelled', 'interrupted'}:
                    self._setup = previous
                    if previous['status'] == 'running':
                        self._setup.update(status='interrupted', message='Setup was interrupted. Cached download bytes are retained.')
        except (OSError, ValueError):
            pass

    @staticmethod
    def _fingerprint(selection):
        return hashlib.sha256(json.dumps(selection.model_dump(), sort_keys=True).encode()).hexdigest()

    def test(self, selection):
        if not self._probe_slot.acquire(blocking=False):
            raise ValueError('Another model test is running. Wait for it to finish before testing again.')
        try:
            result = probe_model(selection)
            token = uuid.uuid4().hex
            with self._lock:
                self._tests = {key: value for key, value in self._tests.items() if value[1] > time.monotonic()}
                if len(self._tests) >= 32: self._tests.pop(next(iter(self._tests)))
                self._tests[token] = (self._fingerprint(selection), time.monotonic() + 600)
            return {**result, 'passed': True, 'test_token': token, 'valid_for_seconds': 600}
        finally:
            self._probe_slot.release()

    def apply(self, request, services, *, automatic_policy=None, setup_apply=False):
        from frib_ds.rag.llm import build_llm_provider
        from frib_ds.storage.reset import DataLifecycleLock
        with self._lock:
            if self._setup.get('status') == 'running' and automatic_policy is None and not setup_apply:
                raise ValueError('Automatic setup is running. Wait for it to finish or cancel it before applying another model.')
            overrides = {'FRIB_LLM_PROVIDER': request.selection.provider, 'FRIB_LLM_MODEL': request.selection.model}
            for key, desired in overrides.items():
                if os.getenv(key) is not None and os.environ[key] != desired:
                    raise ValueError(f'{key} was explicitly set when starting this app. Restart without that override to select a different model in AI Settings.')
            tested = self._tests.get(request.test_token)
            if not tested or tested[0] != self._fingerprint(request.selection) or tested[1] < time.monotonic():
                raise ValueError('Test this exact provider, model and settings successfully before applying. Tests expire after ten minutes.')
            provider = build_llm_provider(request.selection.llm_config())
            with DataLifecycleLock(services.config.data_dir):
                profiles = read_profiles(self.config_dir)
                previous = [entry for entry in profiles['profiles'] if entry['name'] != request.profile_name]
                if automatic_policy is not None or setup_apply:
                    old = selection_from_models(services.config.models).model_dump()
                    if not any(entry['selection'] == old for entry in previous) and len(previous) < 18:
                        previous = [entry for entry in previous if entry['name'] != 'Previous model']
                        previous.append({'name': 'Previous model', 'selection': old, 'capabilities': {}})
                if len(previous) >= 20:
                    raise ValueError('Up to 20 profiles can be saved. Reuse an existing profile name.')
                profiles.update(active_profile=request.profile_name, profiles=[*previous, {'name': request.profile_name, 'selection': request.selection.model_dump(),
                    'verified_at': datetime.now(timezone.utc).isoformat(), 'capabilities': {'chat': True, 'structured_json': True}}])
                profiles['automation'] = automatic_policy if automatic_policy is not None else {**profiles['automation'], 'enabled': False}
                _write_profiles(self.config_dir, profiles)
                services.llm = provider
                services.rag.llm = provider
                services.knowledge.llm = provider
                services.config.models['llm'] = request.selection.llm_config()
            self._tests.pop(request.test_token, None)
        return {'applied': True, 'active': request.selection.model_dump(), 'profile_name': request.profile_name,
                'embeddings_changed': False, 'message': 'Model applied. New answers and drafts use this model; saved records and document search are unchanged.'}

    def can_download(self, server):
        managed = os.getenv('FRIB_MANAGED_OLLAMA_URL')
        return bool(server.provider == 'ollama' and managed and local_url(managed, 'ollama') == server.base_url)

    def download(self, selection, *, automatic=False):
        if not self.can_download(selection):
            raise ValueError('Downloads here use the bundled Ollama server. Start this workspace with START_PROJECT.cmd and use its Ollama address. Manage LM Studio downloads in LM Studio.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}', selection.model) or '..' in selection.model.split('/'):
            raise ValueError('Enter a plain Ollama model identifier, such as a model name and tag.')
        with self._lock:
            if self._setup.get('status') == 'running' and not automatic:
                raise ValueError('Automatic setup is already preparing a model. Wait for it to finish or cancel it first.')
            if any(job['status'] == 'downloading' for job in self._jobs.values()):
                raise ValueError('A model download is already running. Let it finish before starting another.')
            self._jobs = dict(list(self._jobs.items())[-15:])
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {'job_id': job_id, 'model': selection.model, 'status': 'downloading', 'message': 'Starting download', 'completed': 0, 'total': 0, 'cancel_requested': False}
        threading.Thread(target=self._pull, args=(job_id, selection), daemon=True, name='frib-model-download').start()
        return self.download_status(job_id)

    def download_status(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError('This download is unavailable. If the backend restarted, refresh the installed model list or resume the download.')
            return deepcopy(self._jobs[job_id])

    def _pull(self, job_id, selection):
        try:
            success = False
            with _session() as session, session.post(selection.base_url + '/api/pull', json={'model': selection.model, 'stream': True},
                                                    stream=True, timeout=(5, 120), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError(f'Ollama download returned HTTP {response.status_code}.')
                pending = bytearray()
                for chunk in response.iter_content(4096):
                    with self._lock:
                        if self._jobs[job_id].get('cancel_requested'):
                            self._jobs[job_id].update(status='cancelled', message='Download cancelled. Cached bytes are retained for resume.')
                            return
                    pending.extend(chunk)
                    if len(pending) > 65536:
                        raise ValueError('The download server returned an oversized progress message.')
                    while b'\n' in pending:
                        line, _, rest = pending.partition(b'\n')
                        pending = bytearray(rest)
                        if not line.strip():
                            continue
                        update = json.loads(line)
                        if not isinstance(update, dict):
                            raise ValueError('The download server returned invalid progress.')
                        if update.get('error'):
                            raise ValueError(str(update['error'])[:300])
                        total, completed = update.get('total', 0), update.get('completed', 0)
                        if type(total) is not int or type(completed) is not int or min(total, completed) < 0:
                            raise ValueError('The download server returned invalid byte counts.')
                        storage = os.getenv('OLLAMA_MODELS')
                        if total and storage and Path(storage).is_dir():
                            import shutil
                            if shutil.disk_usage(storage).free < max(0,total-completed) + 1024**3:
                                raise ValueError('There is not enough free disk for the remaining model layer plus a 1 GiB reserve. Delete an unused model or free storage, then retry to resume.')
                        success = update.get('status') == 'success'
                        with self._lock:
                            job = self._jobs[job_id]
                            job.update(message=str(update.get('status', 'Downloading'))[:300])
                            if total:
                                job.update(total=total, completed=min(total, completed))
                if not success:
                    raise ValueError('The model download ended before Ollama confirmed success. Try Download again to resume.')
            with self._lock:
                self._jobs[job_id].update(status='completed', message='Download complete. Refresh models, then test this model.')
        except Exception as exc:
            with self._lock:
                self._jobs[job_id].update(status='failed', message=str(exc)[:400])

    def recommendations(self, mode='balanced', refresh=False):
        from frib_ds.ai_hardware import plan_models
        from frib_ds.system_manager import inspect_hardware
        with self._lock:
            cached = self._hardware_cache
        if refresh or not cached or time.monotonic() - cached[0] > 30:
            hardware = inspect_hardware(self.config_dir.parent)
            with self._lock:
                self._hardware_cache = (time.monotonic(), hardware)
        else:
            hardware = cached[1]
        installed = []
        try:
            server = ModelServer(provider='ollama', base_url=os.getenv('FRIB_BUNDLED_OLLAMA_URL', DEFAULT_URLS['ollama']))
            installed = [item['id'] for item in list_models(server)]
        except (requests.RequestException, ValueError):
            pass
        result = plan_models(hardware, installed, mode)
        policy = read_profiles(self.config_dir)['automation']
        result['automatic_enabled'] = policy['enabled']
        result['hardware_changed'] = bool(policy.get('hardware_signature') and policy['hardware_signature'] != result['hardware_signature'])
        return result

    def setup_status(self):
        with self._lock:
            return deepcopy(self._setup)

    def _setup_update(self, **updates):
        with self._lock:
            self._setup.update(updates, updated_at=datetime.now(timezone.utc).isoformat())
            try:
                _write_json_file(preferences_dir(self.config_dir) / 'ai-setup-job.json', self._setup)
            except OSError:
                self._setup['persistence_warning'] = 'Progress could not be saved; the current session will continue.'

    def begin_setup(self, request, services, *, reason='Requested from AI Settings'):
        from frib_ds.ai_hardware import automatic_selection
        plan = self.recommendations(request.mode, refresh=True)
        chosen = AISelection.model_validate(automatic_selection(plan, request.model, os.getenv('FRIB_BUNDLED_OLLAMA_URL', DEFAULT_URLS['ollama'])))
        if not os.getenv('FRIB_DEPENDENCIES_DIR'):
            raise ValueError('Automatic model setup uses the bundled installation. Open this project with START_PROJECT.cmd.')
        with self._lock:
            if self._setup.get('status') == 'running' or any(job['status'] == 'downloading' for job in self._jobs.values()):
                raise ValueError('A model setup or download is already running. Let it finish or cancel it first.')
            self._setup_cancel.clear()
            self._automatic_request = request
            self._setup = {'job_id': uuid.uuid4().hex, 'status': 'running', 'stage': 'checking',
                           'message': 'Preparing a model for this computer', 'request': request.model_dump(),
                           'selection': chosen.model_dump(), 'previous': selection_from_models(services.config.models).model_dump(),
                           'reason': reason, 'hardware_signature': plan['hardware_signature'], 'completed': 0, 'total': 0}
            self._setup_update()
        threading.Thread(target=self._automatic_setup, args=(request, chosen, plan, services), daemon=True, name='frib-automatic-ai-setup').start()
        return self.setup_status()

    def begin_switch(self, request, services):
        selection = request.selection
        if selection.model not in {entry['id'] for entry in list_models(selection)}:
            raise ValueError('This model is not installed on the selected server. Refresh the model list or choose a download from the catalogue.')
        with self._lock:
            if self._setup.get('status') == 'running' or any(job['status'] == 'downloading' for job in self._jobs.values()):
                raise ValueError('Another model setup is running. Let it finish or cancel it first.')
            self._setup_cancel.clear()
            self._setup = {'job_id': uuid.uuid4().hex, 'kind': 'switch', 'status': 'running', 'stage': 'testing',
                           'message': 'Testing the selected model before switching', 'request': request.model_dump(),
                           'selection': selection.model_dump(), 'previous': selection_from_models(services.config.models).model_dump()}
            self._setup_update()
        threading.Thread(target=self._switch_installed, args=(selection, services), daemon=True, name='frib-model-switch').start()
        return self.setup_status()

    def _switch_installed(self, selection, services):
        try:
            tested = self.test(selection)
            if self._setup_cancel.is_set():
                self._setup_update(status='cancelled', stage='cancelled', message='Switch cancelled. Your previous model is still active.')
                return
            self._setup_update(stage='applying', message='Saving and applying the tested model')
            self.apply(ApplySelection(selection=selection, profile_name='My selected AI', test_token=tested['test_token']), services, setup_apply=True)
            self._setup_update(status='completed', stage='completed', message='Ready. Your chosen model is active.')
        except Exception as exc:
            self._setup_update(status='failed', stage='failed', message=str(exc)[:500], previous_model_preserved=True)

    def cancel_setup(self):
        with self._lock:
            if self._setup.get('status') != 'running':
                return self.setup_status()
            if self._setup.get('stage') == 'applying':
                raise ValueError('The tested model is being applied. This final step will finish shortly.')
            self._setup_cancel.set()
            child_job = self._setup.get('download_job')
            if child_job in self._jobs:
                self._jobs[child_job]['cancel_requested'] = True
            self._setup_update(message='Cancelling setup; keeping the previous model')
        return self.setup_status()

    def pause_automation(self):
        with self._lock:
            profiles = read_profiles(self.config_dir)
            profiles['automation']['enabled'] = False
            _write_profiles(self.config_dir, profiles)
            if self._setup.get('status') == 'running' and self._setup.get('kind') not in {'switch','install'}:
                self._automatic_request.auto_adjust = False
                self._setup_update(request=self._automatic_request.model_dump())
        return {'paused': True, 'message': 'Future automatic hardware changes are paused. Your current model stays selected.'}

    def _automatic_setup(self, request, selection, plan, services):
        from frib_ds.ai_storage import AIStorageLock
        try:
            with AIStorageLock():
                self._setup_update(stage='starting', message='Starting the bundled local AI engine')
                started = start_bundled_server()
                if local_url(started['base_url'], 'ollama') != selection.base_url:
                    raise ValueError('The bundled model-server address changed. Refresh the hardware plan and try again.')
                installed = [entry['id'] for entry in list_models(selection)]
                if selection.model not in installed and not self._setup_cancel.is_set():
                    self._setup_update(stage='downloading', message='Downloading the selected model')
                    download = self.download(selection, automatic=True)
                    self._setup_update(download_job=download['job_id'])
                    while True:
                        child = self.download_status(download['job_id'])
                        self._setup_update(message=child['message'], completed=child['completed'], total=child['total'])
                        if self._setup_cancel.is_set() or child['status'] == 'cancelled':
                            self._setup_update(status='cancelled', stage='cancelled', message='Setup cancelled. Your previous model is still active.')
                            return
                        if child['status'] == 'failed':
                            raise ValueError(child['message'])
                        if child['status'] == 'completed':
                            break
                        time.sleep(1)
                if self._setup_cancel.is_set():
                    self._setup_update(status='cancelled', stage='cancelled', message='Setup cancelled. Your previous model is still active.')
                    return
                self._setup_update(stage='testing', message='Checking a real answer and structured JSON compatibility')
                tested = self.test(selection)
                if self._setup_cancel.is_set():
                    self._setup_update(status='cancelled', stage='cancelled', message='Setup cancelled. Your previous model is still active.')
                    return
                self._setup_update(stage='applying', message='Applying the tested model and saving your preference')
                policy = {'enabled': request.auto_adjust, 'mode': request.mode, 'hardware_signature': plan['hardware_signature'],
                          'checked_at': datetime.now(timezone.utc).isoformat()}
                self.apply(ApplySelection(selection=selection, profile_name='My selected AI' if request.model else 'Automatic AI', test_token=tested['test_token']), services, automatic_policy=policy)
                self._setup_update(status='completed', stage='completed', message='Ready. The tested model is active and your document search is unchanged.')
        except Exception as exc:
            self._setup_update(status='failed', stage='failed', message=str(exc)[:500], previous_model_preserved=True)

    def check_automatic_hardware(self, services):
        policy = read_profiles(self.config_dir)['automation']
        status = self.setup_status()
        if status.get('status') == 'running':
            return
        if status.get('status') == 'interrupted' and status.get('request'):
            if status.get('kind') == 'install':
                from frib_ds.model_library import get_model_library, NewModelRequest
                get_model_library(self).install(NewModelRequest.model_validate(status['request']),services)
            elif status.get('kind') == 'switch':
                self.begin_switch(InstalledModelSwitch.model_validate(status['request']), services)
            else:
                self.begin_setup(AutomaticSetup.model_validate(status['request']), services, reason='Resuming interrupted setup')
            return
        if not policy.get('enabled'):
            return
        plan = self.recommendations(policy['mode'], refresh=True)
        if status.get('status') == 'failed' and status.get('hardware_signature') == plan['hardware_signature']:
            return
        if plan.get('blocked_reason') or plan['hardware_signature'] == policy.get('hardware_signature'):
            return
        current = selection_from_models(services.config.models)
        if current.provider == 'ollama' and plan['recommended']['id'] == current.model:
            with self._lock:
                profiles = read_profiles(self.config_dir)
                profiles['automation']['hardware_signature'] = plan['hardware_signature']
                _write_profiles(self.config_dir, profiles)
            return
        self.begin_setup(AutomaticSetup(mode=policy['mode'], auto_adjust=True), services, reason='Hardware change detected')

    def watch_hardware(self, services):
        with self._lock:
            if self._watching:
                return
            self._watching = True
        def watch():
            while True:
                try:
                    self.check_automatic_hardware(services)
                except Exception:
                    # A temporarily unavailable scan must never replace a working model.
                    pass
                time.sleep(60)
        threading.Thread(target=watch, daemon=True, name='frib-hardware-model-watcher').start()


_managers = {}
_managers_lock = threading.Lock()


def get_ai_manager(config_dir):
    key = str(settings_path(config_dir).resolve())
    with _managers_lock:
        return _managers.setdefault(key, AISettingsManager(config_dir))
