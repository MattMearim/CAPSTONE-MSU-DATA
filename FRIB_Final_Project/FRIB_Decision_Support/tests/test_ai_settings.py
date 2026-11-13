"""Verified chat-model switching must preserve evidence and embedding state."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
import pytest

from frib_ds import ai_settings as ai
from frib_ds.config import Config
from frib_ds.rag.llm import LMStudioProvider, OllamaProvider


def selection(**updates):
    return ai.AISelection(**{'provider': 'ollama', 'model': 'qwen3:8b', 'base_url': 'http://127.0.0.1:11434', **updates})


@pytest.fixture
def services(tmp_path):
    config = Config(tmp_path / 'config', create_dirs=False)
    config.data_dir.mkdir(parents=True)
    embedding = object()
    store = object()
    old = OllamaProvider('http://127.0.0.1:11434', 'qwen3:8b')
    return SimpleNamespace(config=config, embedding=embedding, vector=store, llm=old,
                           rag=SimpleNamespace(llm=old, embedding=embedding, store=store),
                           knowledge=SimpleNamespace(llm=old), processors=SimpleNamespace(domains=lambda: ['rf']))


@pytest.mark.parametrize('url', ['https://127.0.0.1:11434', 'http://example.com:11434', 'file:///tmp/model',
                               'http://user:secret@localhost:11434', 'http://localhost:80',
                               'http://localhost:11434/redirect', 'http://localhost:11434?x=1', 'http://localhost:11434#x'])
def test_model_servers_cannot_reach_external_hosts_credentials_or_paths(url):
    with pytest.raises(ValueError):
        selection(base_url=url)


def test_lmstudio_url_and_chat_options_are_validated():
    item = selection(provider='lmstudio', base_url='http://localhost:1234', model='local/chat-model')
    assert item.base_url == 'http://127.0.0.1:1234/v1'
    assert item.llm_config()['lmstudio_base_url'] == item.base_url
    with pytest.raises(ValueError):
        selection(max_output_tokens=4096)
    with pytest.raises(ValueError):
        ai.AISelection.model_validate({**item.model_dump(), 'embedding_model': 'other'})


def test_successful_switch_updates_both_chat_consumers_and_survives_restart(tmp_path, services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True, 'sample': 'READY'})
    before_embedding = services.embedding
    before_store = services.vector
    embedding_config = deepcopy(services.config.models['embeddings'])
    chosen = selection(provider='lmstudio', base_url='http://127.0.0.1:1234/v1', model='different/model')
    tested = manager.test(chosen)
    result = manager.apply(ai.ApplySelection(selection=chosen, profile_name='Desktop model', test_token=tested['test_token']), services)
    assert result['applied'] and not result['embeddings_changed']
    assert isinstance(services.llm, LMStudioProvider)
    assert services.rag.llm is services.llm is services.knowledge.llm
    assert services.embedding is before_embedding and services.vector is before_store
    assert services.config.models['embeddings'] == embedding_config
    restarted = Config(services.config.config_dir, create_dirs=False)
    assert restarted.models['llm']['provider'] == 'lmstudio'
    assert restarted.models['llm']['model'] == 'different/model'
    assert ai.read_profiles(services.config.config_dir)['active_profile'] == 'Desktop model'


def test_untested_changed_or_expired_model_cannot_replace_the_active_provider(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True})
    old = services.llm
    tested = manager.test(selection())
    for candidate, token in [(selection(model='changed'), tested['test_token']), (selection(), 'unknown')]:
        with pytest.raises(ValueError, match='Test this exact'):
            manager.apply(ai.ApplySelection(selection=candidate, profile_name='Bad', test_token=token), services)
    manager._tests[tested['test_token']] = (manager._fingerprint(selection()), time.monotonic() - 1)
    with pytest.raises(ValueError, match='Test this exact'):
        manager.apply(ai.ApplySelection(selection=selection(), profile_name='Expired', test_token=tested['test_token']), services)
    assert services.llm is old
    assert not ai.settings_path(services.config.config_dir).exists()


def test_failed_structured_probe_and_failed_save_keep_active_model(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    old = services.llm
    monkeypatch.setattr(ai, 'probe_model', lambda item: (_ for _ in ()).throw(ValueError('Invalid JSON')))
    with pytest.raises(ValueError):
        manager.test(selection())
    assert not manager._tests
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True})
    tested = manager.test(selection())
    monkeypatch.setattr(ai, '_write_profiles', lambda *args: (_ for _ in ()).throw(OSError('Disk full')))
    with pytest.raises(OSError):
        manager.apply(ai.ApplySelection(selection=selection(), profile_name='Save failed', test_token=tested['test_token']), services)
    assert services.rag.llm is old and services.knowledge.llm is old


def test_profile_replacement_and_environment_override(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True})
    for name in ('first', 'second'):
        chosen = selection(model=name)
        tested = manager.test(chosen)
        manager.apply(ai.ApplySelection(selection=chosen, profile_name='Reusable', test_token=tested['test_token']), services)
    assert len(ai.read_profiles(services.config.config_dir)['profiles']) == 1
    monkeypatch.setenv('FRIB_LLM_MODEL', 'explicit-command-line-model')
    assert Config(services.config.config_dir, create_dirs=False).models['llm']['model'] == 'explicit-command-line-model'


def test_switch_waits_for_inflight_evidence_request(services, monkeypatch):
    from frib_ds.storage.reset import DataLifecycleLock
    manager = ai.AISettingsManager(services.config.config_dir)
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True})
    chosen = selection(model='next-model')
    tested = manager.test(chosen)
    request = ai.ApplySelection(selection=chosen, profile_name='After current request', test_token=tested['test_token'])
    old = services.llm
    finished = threading.Event()
    failures = []
    def switch():
        try:
            manager.apply(request, services)
        except Exception as exc:
            failures.append(exc)
        finally:
            finished.set()
    with DataLifecycleLock(services.config.data_dir):
        worker = threading.Thread(target=switch, daemon=True)
        worker.start()
        assert not finished.wait(0.1)
        assert services.llm is old
    assert finished.wait(5)
    worker.join(timeout=1)
    assert not failures
    assert services.llm.model == 'next-model'


def test_atomic_profile_write_failure_keeps_previous_file(tmp_path, monkeypatch):
    first = {'schema_version': '1.0', 'active_profile': 'First', 'profiles': [{'name': 'First', 'selection': selection().model_dump()}]}
    ai._write_profiles(tmp_path, first)
    original = ai.settings_path(tmp_path).read_bytes()
    monkeypatch.setattr(ai.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('Read-only disk')))
    with pytest.raises(OSError):
        ai._write_profiles(tmp_path, {**first, 'active_profile': None})
    assert ai.settings_path(tmp_path).read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))


def test_private_launcher_uses_saved_choice_without_forcing_a_model(tmp_path, monkeypatch):
    import importlib.util
    workspace = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('tested_private_ai_launcher', workspace / 'dependencies/run_frib.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    project = tmp_path / 'project'
    config = project / 'config'
    chosen = selection(provider='lmstudio', base_url='http://127.0.0.1:1234/v1', model='selected-studio-model')
    ai._write_profiles(config, {'schema_version': '1.0', 'active_profile': 'Studio',
                              'profiles': [{'name': 'Studio', 'selection': chosen.model_dump()}]})
    monkeypatch.setattr(launcher, 'PROJECT', project)
    monkeypatch.delenv('FRIB_LLM_PROVIDER', raising=False)
    monkeypatch.delenv('FRIB_LLM_MODEL', raising=False)
    assert 'FRIB_LLM_PROVIDER' not in launcher.environment()
    assert 'FRIB_LLM_MODEL' not in launcher.environment()
    assert launcher.selected_ai() == chosen


def test_native_model_check_supports_lmstudio_without_starting_ollama(tmp_path, monkeypatch):
    from frib_ds import local_ai
    from frib_ds import config as configuration
    chosen = selection(provider='lmstudio', base_url='http://127.0.0.1:1234/v1', model='studio-model')
    models = {'llm': chosen.llm_config(), 'embeddings': {'provider': 'sentence_transformers', 'model': 'all-MiniLM-L6-v2'}}
    monkeypatch.setattr(configuration, 'Config', lambda **kwargs: SimpleNamespace(models=models))
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True, 'sample': 'READY'})
    monkeypatch.setattr(local_ai, 'check_embedding', lambda _models: {'provider': 'sentence_transformers', 'model': 'all-MiniLM-L6-v2', 'dimensions': 384})
    monkeypatch.setattr(local_ai, 'ensure_ollama', lambda *args, **kwargs: pytest.fail('LM Studio must not start Ollama'))
    assert local_ai.main([]) == 0


@pytest.fixture
def local_model_server():
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def answer(self, value, status=200):
            payload = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def do_GET(self):
            if self.path == '/api/tags':
                self.answer({'models': [{'name': 'selected-model', 'size': 1024, 'details': {'parameter_size': 'small'}}]})
            elif self.path == '/v1/models':
                self.answer({'data': [{'id': 'selected-model'}]})
            else:
                self.answer({}, 404)
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append((self.path, payload))
            if self.path == '/api/pull':
                self.answer(b'{"status":"pulling","total":100,"completed":40}\n{"status":"success"}\n')
            elif self.path == '/api/chat':
                self.answer({'message': {'content': '{"ready":true}' if payload.get('format') else 'READY'}})
            elif self.path == '/v1/chat/completions':
                self.answer({'choices': [{'message': {'content': '{"ready":true}' if payload.get('response_format') else 'READY'}}]})
            else:
                self.answer({}, 404)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
def test_actual_http_protocol_lists_models_and_checks_chat_and_json(local_model_server, provider):
    base, captured = local_model_server
    chosen = selection(provider=provider, base_url=base, model='selected-model')
    assert ai.list_models(chosen)[0]['id'] == 'selected-model'
    result = ai.probe_model(chosen)
    assert result['chat'] and result['structured_json']
    assert len(captured) == 2
    assert all(payload['model'] == 'selected-model' for _, payload in captured)
    if provider == 'lmstudio':
        assert captured[-1][1]['response_format']['json_schema']['strict'] is True
    else:
        assert captured[-1][1]['format']['additionalProperties'] is False


def test_download_progress_and_errors_are_scoped_to_the_managed_server(local_model_server, tmp_path, monkeypatch):
    base, captured = local_model_server
    manager = ai.AISettingsManager(tmp_path)
    chosen = selection(base_url=base, model='selected-model')
    with pytest.raises(ValueError, match='bundled'):
        manager.download(chosen)
    monkeypatch.setenv('FRIB_MANAGED_OLLAMA_URL', base)
    job = manager.download(chosen)
    deadline = time.monotonic() + 5
    while manager.download_status(job['job_id'])['status'] == 'downloading' and time.monotonic() < deadline:
        time.sleep(0.02)
    result = manager.download_status(job['job_id'])
    assert result['status'] == 'completed' and result['completed'] == 40 and result['total'] == 100
    with pytest.raises(KeyError):
        manager.download_status('not-an-owned-job')
    assert captured[0][0] == '/api/pull'


def test_api_apply_requires_successful_test_and_exposes_active_choice(services, monkeypatch):
    from frib_ds.api import main as api
    from frib_ds.config import get_config
    monkeypatch.setattr(api, 'get_services', lambda: services)
    monkeypatch.setattr(api, 'get_config', lambda: services.config)
    monkeypatch.setattr(ai, 'probe_model', lambda item: {'chat': True, 'structured_json': True})
    chosen = selection(model='newly-selected').model_dump()
    with TestClient(api.app) as client:
        assert client.post('/system/ai/apply', json={'selection': chosen, 'profile_name': 'New', 'test_token': 'missing'}).status_code == 400
        token = client.post('/system/ai/test', json=chosen).json()['test_token']
        applied = client.post('/system/ai/apply', json={'selection': chosen, 'profile_name': 'New', 'test_token': token})
        assert applied.status_code == 200, applied.text
        assert client.get('/system/ai').json()['active']['model'] == 'newly-selected'
        assert client.get('/health').json()['llm_model'] == 'newly-selected'
        assert client.post('/system/ai/test', json={**chosen, 'base_url': 'http://external.invalid:8000'}).status_code == 422
