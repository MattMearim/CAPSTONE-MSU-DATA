"""Read-only measured resource snapshots. Model allocations and process RAM overlap."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import psutil

from frib_ds.ai_settings import ModelServer, _json_get, list_models, selection_from_models


def _bytes(value):
    return value if type(value) is int and value >= 0 else None


def ollama_models(installed, loaded, active):
    """Keep on-disk bytes distinct from Ollama's runtime allocation estimates."""
    running = {entry.get('name') or entry.get('model'): entry for entry in loaded if isinstance(entry, dict)}
    result = []
    known = {entry['id']: entry for entry in installed}
    for name in running:
        if isinstance(name, str):
            known.setdefault(name, {'id': name, 'size_bytes': None})
    for name, entry in known.items():
        runtime = running.get(name)
        allocation = _bytes(runtime.get('size')) if runtime else 0
        gpu = _bytes(runtime.get('size_vram')) if runtime else 0
        result.append({'model': name, 'provider':'ollama', 'selected': active.provider == 'ollama' and active.model == name,
                       'loaded': runtime is not None, 'disk_bytes': _bytes(entry.get('size_bytes')),
                       'allocation_bytes': allocation, 'gpu_bytes': gpu,
                       'non_gpu_bytes': max(0, allocation - gpu) if allocation is not None and gpu is not None else None,
                       'context_length': runtime.get('context_length') if runtime else None})
    return sorted(result, key=lambda entry: entry['model'])


def _gpu():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return {'devices': [], 'available': False, 'note': 'GPU telemetry unavailable; this does not mean zero use.'}
    try:
        result = subprocess.run([executable, '--query-gpu=name,memory.total,memory.used,utilization.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        devices = []
        for row in csv.reader(io.StringIO(result.stdout[:10000])):
            if len(row) != 4:
                continue
            total, used, percent = map(float, row[1:])
            if not all(math.isfinite(value) and value >= 0 for value in (total, used, percent)):
                continue
            devices.append({'name': row[0].strip(), 'total_bytes': int(total * 1024**2),
                            'used_bytes': int(used * 1024**2), 'utilization_percent': min(percent, 100)})
        return {'devices': devices, 'available': result.returncode == 0 and bool(devices),
                'note': 'Device-wide totals include other applications; GPU memory also appears in the model table.'}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'devices': [], 'available': False, 'note': 'GPU telemetry unavailable; this does not mean zero use.'}


def directory_bytes(path):
    """Logical file sizes, skipping links/reparse points and duplicate file IDs."""
    total, count, seen = 0, 0, set()
    path = Path(path)
    if not path.exists():
        return None
    try:
        for root, directories, files in os.walk(path, followlinks=False):
            directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()
                              and not (getattr((Path(root) / name).lstat(), 'st_file_attributes', 0) & 0x400)]
            for name in files:
                info = (Path(root) / name).lstat()
                if getattr(info, 'st_file_attributes', 0) & 0x400 or (Path(root) / name).is_symlink():
                    continue
                key = (info.st_dev, info.st_ino)
                if key not in seen:
                    total += info.st_size
                    seen.add(key)
                count += 1
                if count > 200000:
                    return None
        return total
    except OSError:
        return None


def _service_processes(dependencies):
    roots = [('API + document search', psutil.Process())]
    if dependencies:
        try:
            path = Path(dependencies) / 'runtime/workspace.json'
            state = json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size < 100000 else {}
            candidates = [('Launcher', state.get('supervisor')),
                          *[('API + document search' if name == 'backend' else name.title(), value) for name, value in state.get('services', {}).items()]]
            for role, identity in candidates:
                if not isinstance(identity, dict):
                    continue
                process = psutil.Process(identity['pid'])
                expected = identity.get('creation_time_filetime')
                created = (expected / 10_000_000 - 11644473600) if type(expected) is int else None
                if (created is not None and abs(process.create_time() - created) < 1
                        and os.path.normcase(process.exe()) == os.path.normcase(identity.get('executable', ''))):
                    roots.append((role, process))
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
    # Service roots include venv launchers; assign children before walking the
    # supervisor to avoid counting each service again under the supervisor.
    records, seen = [], set()
    roots.sort(key=lambda item: item[0] == 'Launcher')
    for role, process in roots:
        try:
            for child in [process, *process.children(recursive=True)]:
                if child.pid not in seen:
                    records.append((role, child, child.cpu_times()))
                    seen.add(child.pid)
        except psutil.Error:
            continue
    return records


_lock = threading.Lock()
_snapshot_cache = None
_disk_cache = None
_disk_scan_key = None


def _scan_storage(key, locations):
    global _disk_cache, _disk_scan_key
    try:
        storage = [{'component': label, 'bytes': directory_bytes(path)} for label, path in locations]
        with _lock:
            _disk_cache = (key, time.monotonic(), storage)
    finally:
        with _lock:
            _disk_scan_key = None


def resource_snapshot(services, *, include_storage=True):
    global _snapshot_cache, _disk_cache, _disk_scan_key
    with _lock:
        if (_snapshot_cache and time.monotonic() - _snapshot_cache[0] < 2
                and (not include_storage or _snapshot_cache[2])):
            return _snapshot_cache[1]
        dependencies = os.getenv('FRIB_DEPENDENCIES_DIR')
        records = _service_processes(dependencies)
        cpu_start = time.monotonic()
        cpu = psutil.cpu_percent(interval=0.25)
        elapsed = time.monotonic() - cpu_start
        cores = psutil.cpu_count() or 1
        groups = {}
        for role, process, before in records:
            try:
                memory, after = process.memory_info(), process.cpu_times()
                delta = max(0, after.user + after.system - before.user - before.system)
                group = groups.setdefault(role, {'component': role, 'resident_bytes': 0, 'private_bytes': 0, 'cpu_percent': 0, 'processes': 0})
                group['resident_bytes'] += memory.rss
                group['private_bytes'] += getattr(memory, 'private', 0)
                group['cpu_percent'] += min(100, 100 * delta / elapsed / cores)
                group['processes'] += 1
            except psutil.Error:
                continue
        active = selection_from_models(services.config.models)
        models, model_error = [], None
        try:
            server = ModelServer(provider='ollama', base_url=os.getenv('FRIB_BUNDLED_OLLAMA_URL',
                                 active.base_url if active.provider == 'ollama' else 'http://127.0.0.1:11434'))
            installed = list_models(server, timeout=(0.5, 1))
            loaded = _json_get(server.base_url + '/api/ps', timeout=(0.5, 1)).get('models')
            if not isinstance(loaded, list):
                raise ValueError('Invalid running-model list')
            models = ollama_models(installed, loaded, active)
        except Exception:
            model_error = 'Ollama telemetry is unavailable. Model use is unknown, not zero.'
        if active.provider == 'lmstudio':
            models.append({'model': active.model, 'provider':'lmstudio', 'selected': True, 'loaded': None, 'disk_bytes': None,
                           'allocation_bytes': None, 'gpu_bytes': None, 'non_gpu_bytes': None})
        from frib_ds.quality_agent_settings import read_quality_settings
        quality=read_quality_settings(services.config.config_dir) if hasattr(services.config,'config_dir') else None
        for entry in models: entry['roles']=['chat'] if entry['selected'] else []
        if quality and quality.selection:
            selection=quality.selection
            match=next((entry for entry in models if entry['model']==selection.model and entry.get('provider')==selection.provider),None)
            if match is None and selection.provider=='lmstudio':
                match={'model':selection.model,'provider':'lmstudio','selected':False,'loaded':None,'disk_bytes':None,'allocation_bytes':None,'gpu_bytes':None,'non_gpu_bytes':None,'roles':[]}
                models.append(match)
            if match is not None: match['roles'].append('quality')
        disk_key = (dependencies, str(services.config.data_dir), os.getenv('FRIB_EMBEDDING_CACHE'))
        locations = [('Workspace data / index', services.config.data_dir)]
        if dependencies:
            root = Path(dependencies)
            locations += [('Chat model files (shared store)', root / 'ai/models/ollama'),
                          ('Python + installed packages', root / 'venv'), ('Python runtime', root / 'python'),
                          ('Ollama runtime', root / 'ollama'),
                          ('MiniLM embedding cache', root / 'ai/cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2')]
        stale_disk = not _disk_cache or _disk_cache[0] != disk_key or time.monotonic() - _disk_cache[1] > 60
        if include_storage and stale_disk and _disk_scan_key is None:
            _disk_scan_key = disk_key
            threading.Thread(target=_scan_storage, args=(disk_key, locations), daemon=True, name='frib-storage-measurement').start()
        storage = _disk_cache[2] if _disk_cache and _disk_cache[0] == disk_key else [{'component': label, 'bytes': None} for label, _ in locations]
        memory = psutil.virtual_memory()
        result = {'measured_at': datetime.now(timezone.utc).isoformat(), 'sample_seconds': round(elapsed, 3),
                  'active': active.model_dump(), 'system': {'ram_total_bytes': memory.total, 'ram_used_bytes': memory.total - memory.available,
                  'ram_available_bytes': memory.available, 'cpu_percent': cpu, 'logical_cores': cores},
                  'processes': list(groups.values()), 'models': models, 'model_error': model_error,
                  'gpu': _gpu(), 'storage': storage, 'storage_scanning': _disk_scan_key == disk_key,
                  'quality_agent':{'enabled':bool(quality and quality.enabled),'model':quality.selection.model if quality and quality.selection else None,
                                   'current_run':getattr(getattr(services,'quality_agent',None),'current_run',None)},
                  'notes': ['RAM is resident working set; shared pages can appear in more than one process. Process CPU is normalized to the whole computer.',
                            'Model allocation is reported by Ollama; its non-GPU portion is allocation minus GPU bytes. These values overlap process RAM and GPU totals; do not add them together.',
                            'MiniLM runs inside the API process on CPU. Its exact RAM cannot be separated from the API by process monitoring.',
                            'Installed models can be unloaded while idle. Unloaded models use disk but have no active Ollama model allocation. LM Studio model allocation is unavailable here.',
                            'Storage uses logical file sizes, skips links, and refreshes about once a minute. Shared model layers make per-model file sizes non-additive.']}
        _snapshot_cache = (time.monotonic(), result, include_storage)
        return result
