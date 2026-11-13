"""The live monitor is read-only and independent of long evidence requests."""
from types import SimpleNamespace
import threading

from fastapi.testclient import TestClient

from frib_ds import ai_resources as resources
from frib_ds.storage.reset import DataLifecycleLock
from test_api_lifecycle import api_environment


def test_monitor_assets_are_local_read_only_and_have_content_security_policy(api_environment):
    client, _, _ = api_environment
    for path, content_type in [('/system/ai/monitor', 'text/html'),
                              ('/system/ai/monitor/monitor.js', 'text/javascript'),
                              ('/system/ai/monitor/monitor.css', 'text/css')]:
        response = client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers['content-type']
        assert "script-src 'self'" in response.headers['content-security-policy']
        assert "connect-src 'self'" in response.headers['content-security-policy']
        assert response.headers['cache-control'] == 'no-store'
        assert client.post(path).status_code == 405
    assert client.get('/system/ai/monitor/other.js').status_code == 422
    assert client.get('/system/ai/monitor', headers={'Origin': 'https://unrelated.invalid'}).status_code == 403


def test_live_resources_can_refresh_while_evidence_lifecycle_is_busy(api_environment, monkeypatch):
    client, state, _ = api_environment
    config = state['services'].config
    monkeypatch.setattr(resources, 'resource_snapshot', lambda services, **kwargs: {'live': True, 'storage': kwargs['include_storage']})
    locked, release = threading.Event(), threading.Event()
    def work():
        with DataLifecycleLock(config.data_dir):
            locked.set()
            release.wait(5)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    assert locked.wait(2)
    try:
        response = client.get('/system/ai/resources?storage=false')
        assert response.status_code == 200
        assert response.json() == {'live': True, 'storage': False}
        assert not release.is_set() and worker.is_alive()
    finally:
        release.set()
        worker.join(2)


def test_light_monitor_requests_never_start_a_storage_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, '_snapshot_cache', None)
    monkeypatch.setattr(resources, '_disk_cache', None)
    monkeypatch.setattr(resources, '_disk_scan_key', None)
    monkeypatch.setattr(resources, 'list_models', lambda _, **kwargs: [])
    monkeypatch.setattr(resources, '_json_get', lambda _, **kwargs: {'models': []})
    monkeypatch.setattr(resources, '_gpu', lambda: {'available': False, 'devices': [], 'note': 'Unavailable'})
    monkeypatch.setattr(resources, '_scan_storage', lambda *args: (_ for _ in ()).throw(AssertionError('Live monitor must not scan files')))
    services = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, models={'llm': {'provider': 'ollama', 'model': 'x'}}))
    report = resources.resource_snapshot(services, include_storage=False)
    assert report['system']['ram_total_bytes'] > 0
    assert resources._disk_scan_key is None
    assert report['storage_scanning'] is False
