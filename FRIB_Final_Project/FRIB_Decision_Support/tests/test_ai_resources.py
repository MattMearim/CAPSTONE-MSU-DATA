from types import SimpleNamespace
import threading
import time

from frib_ds.ai_resources import ollama_models, directory_bytes
from frib_ds import ai_resources as resources
from frib_ds.ai_settings import AISelection


def test_disk_loaded_and_gpu_allocations_are_kept_separate():
    active = AISelection(provider='ollama', base_url='http://127.0.0.1:11434', model='chosen:4b')
    result = ollama_models([{'id': 'chosen:4b', 'size_bytes': 2500}, {'id': 'idle:8b', 'size_bytes': 5200}],
                           [{'name': 'chosen:4b', 'size': 3000, 'size_vram': 2400, 'context_length': 4096}], active)
    loaded, idle = result
    assert loaded['selected'] and loaded['loaded'] and loaded['non_gpu_bytes'] == 600
    assert idle['disk_bytes'] == 5200 and idle['allocation_bytes'] == 0 and idle['loaded'] is False
    assert loaded['disk_bytes'] != loaded['allocation_bytes']


def test_bad_runtime_values_are_unknown_not_false_zero():
    active = AISelection(provider='ollama', base_url='http://127.0.0.1:11434', model='x')
    item = ollama_models([{'id': 'x', 'size_bytes': 10}], [{'name': 'x', 'size': 'bad', 'size_vram': -1}], active)[0]
    assert item['loaded'] and item['allocation_bytes'] is None and item['gpu_bytes'] is None and item['non_gpu_bytes'] is None


def test_storage_missing_and_real_files(tmp_path):
    assert directory_bytes(tmp_path / 'missing') is None
    (tmp_path / 'file').write_bytes(b'12345')
    assert directory_bytes(tmp_path) == 5


def test_unavailable_server_is_explicit_and_lmstudio_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, '_snapshot_cache', None)
    monkeypatch.setattr(resources, '_disk_cache', None)
    monkeypatch.setattr(resources, 'list_models', lambda _, **kwargs: (_ for _ in ()).throw(ValueError('offline')))
    monkeypatch.setattr(resources, '_gpu', lambda: {'available': False, 'devices': [], 'note': 'Unavailable'})
    services = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, models={'llm': {'provider': 'lmstudio', 'model': 'local-model'}}))
    report = resources.resource_snapshot(services)
    assert report['model_error']
    assert report['models'][0]['loaded'] is None and report['models'][0]['allocation_bytes'] is None
    assert report['system']['ram_total_bytes'] > 0
    assert report['processes'][0]['component'] == 'API + document search'
    assert report['processes'][0]['resident_bytes'] > 0


def test_slow_storage_scan_does_not_block_live_memory_readings(tmp_path, monkeypatch):
    # A cloud-synced directory can take seconds to enumerate. A real blocked
    # worker must not hold the live telemetry request until it finishes.
    deadline = time.monotonic() + 5
    while resources._disk_scan_key is not None and time.monotonic() < deadline:
        time.sleep(.01)
    started, release = threading.Event(), threading.Event()
    def slow_size(path):
        started.set()
        release.wait(4)
        return 123
    monkeypatch.setattr(resources, '_snapshot_cache', None)
    monkeypatch.setattr(resources, '_disk_cache', None)
    monkeypatch.setattr(resources, 'directory_bytes', slow_size)
    monkeypatch.setattr(resources, 'list_models', lambda _, **kwargs: [])
    monkeypatch.setattr(resources, '_json_get', lambda _, **kwargs: {'models': []})
    monkeypatch.setattr(resources, '_gpu', lambda: {'available': False, 'devices': [], 'note': 'Unavailable'})
    services = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, models={'llm': {'provider': 'ollama', 'model': 'x'}}))
    before = time.monotonic()
    try:
        report = resources.resource_snapshot(services)
        assert time.monotonic() - before < 2
        assert started.wait(1) and report['storage_scanning']
        assert report['system']['ram_total_bytes'] > 0
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while resources._disk_scan_key is not None and time.monotonic() < deadline:
            time.sleep(.01)
