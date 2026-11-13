"""Conservative local-model planning; capacity estimates are checked by real probes."""
from __future__ import annotations

import hashlib
import json
import math

MODES = {'balanced': 'Recommended balance', 'speed': 'Prefer speed', 'capacity': 'Prefer a larger model'}
# Download sizes are rounded vendor catalogue values; RAM/VRAM limits are our planning estimates.
CATALOG = (
    {'id': 'qwen3:1.7b', 'name': 'Compact', 'download_gb': 1.4, 'ram_gib': 7, 'gpu_gib': 2.5, 'gpu_ram_gib': 7},
    {'id': 'qwen3:4b', 'name': 'Fast', 'download_gb': 2.5, 'ram_gib': 11, 'gpu_gib': 3.5, 'gpu_ram_gib': 11},
    {'id': 'qwen3:8b', 'name': 'Standard', 'download_gb': 5.2, 'ram_gib': 15, 'gpu_gib': 7, 'gpu_ram_gib': 15},
    {'id': 'qwen3:14b', 'name': 'Expanded', 'download_gb': 9.3, 'ram_gib': 23, 'gpu_gib': 13, 'gpu_ram_gib': 23},
    {'id': 'qwen3:32b', 'name': 'Large', 'download_gb': 20.0, 'ram_gib': 47, 'gpu_gib': 23, 'gpu_ram_gib': 23},
)

# Explicit alternatives for the model picker; the automatic policy stays on its
# existing, size-ordered Qwen family so choosing a family remains the user's choice.
ALTERNATIVES = (
    {'id': 'llama3.2:3b', 'name': 'Llama 3.2 3B', 'download_gb': 2.0, 'ram_gib': 9, 'gpu_gib': 3, 'gpu_ram_gib': 9},
    {'id': 'phi4-mini:3.8b', 'name': 'Phi-4 Mini', 'download_gb': 2.5, 'ram_gib': 11, 'gpu_gib': 3.5, 'gpu_ram_gib': 11},
    {'id': 'gemma3:4b', 'name': 'Gemma 3 4B', 'download_gb': 3.4, 'ram_gib': 12, 'gpu_gib': 5, 'gpu_ram_gib': 12},
)


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def hardware_signature(hardware):
    summary = {'architecture': hardware.get('architecture'), 'ram_gib': _number(hardware.get('memory', {}).get('total_gib')),
               'cpu': hardware.get('cpu', {}).get('model'), 'cores': hardware.get('cpu', {}).get('logical_cores'),
               'gpu': sorted((str(item.get('name', ''))[:200], _number(item.get('memory_gib')) or 0) for item in hardware.get('gpu', {}).get('devices', []))}
    return hashlib.sha256(json.dumps(summary, sort_keys=True, allow_nan=False).encode()).hexdigest()


def plan_models(hardware, installed=(), mode='balanced'):
    if mode not in MODES:
        raise ValueError('Choose one of the available performance preferences.')
    ram = _number(hardware.get('memory', {}).get('total_gib'))
    disk = _number(hardware.get('disk', {}).get('free_gib'))
    available = _number(hardware.get('memory', {}).get('available_gib'))
    gpu = max((_number(item.get('memory_gib')) or 0 for item in hardware.get('gpu', {}).get('devices', [])), default=0)
    installed = set(installed)
    options = []
    for index, original in enumerate((*CATALOG, *ALTERNATIVES)):
        entry = dict(original)
        accelerated = gpu >= entry['gpu_gib'] and ram is not None and ram >= entry['gpu_ram_gib']
        memory_fits = ram is not None and (ram >= entry['ram_gib'] or accelerated)
        disk_needed = 0 if entry['id'] in installed else entry['download_gb'] * 1e9 / 1024**3 * 1.2 + 2
        space_fits = disk is not None and disk >= disk_needed
        entry.update(installed=entry['id'] in installed, accelerated=accelerated, automatic=index < len(CATALOG),
                     eligible=bool(memory_fits and space_fits), estimated_free_disk_needed_gib=round(disk_needed, 1), rank=index)
        if not memory_fits:
            entry['fit'] = 'More memory needed'
        elif not space_fits:
            entry['fit'] = 'More free disk needed'
        elif accelerated:
            entry['fit'] = 'Likely GPU fit'
        else:
            entry['fit'] = 'Fits system memory; may use slower CPU processing'
        entry['source'] = 'https://ollama.com/library/' + entry['id']
        options.append(entry)
    eligible = [entry for entry in options if entry['eligible'] and entry['automatic']]
    accelerated = [entry for entry in eligible if entry['accelerated']]
    if mode == 'capacity':
        chosen = eligible[-1] if eligible else None
    else:
        # Without a detected accelerator, favour responsiveness over the largest RAM-fitting file.
        cpu_limit = 2 if ram is not None and ram >= 63 else 1
        balanced = accelerated[-1] if accelerated else next((entry for entry in reversed(eligible) if entry['rank'] <= cpu_limit), None)
        chosen = balanced
        if mode == 'speed' and balanced:
            chosen = next((entry for entry in reversed(eligible) if entry['rank'] < balanced['rank']), balanced)
    blocked = None
    if ram is None or disk is None:
        blocked = 'Memory or free disk could not be detected. Refresh the hardware check before automatic setup.'
    elif not chosen:
        blocked = 'There is not enough detected memory or free disk for the supported local models. Your current model has been kept.'
    elif available is not None and available < 2:
        blocked = 'Less than 2 GiB of memory is currently available. Close some other applications, then try again.'
    return {'hardware': hardware, 'hardware_signature': hardware_signature(hardware), 'mode': mode,
            'modes': MODES, 'options': options, 'recommended': chosen, 'blocked_reason': blocked,
            'note': 'Memory fit is an estimate. Setup checks real chat and structured JSON before changing the active model.'}


def automatic_selection(plan, model=None, base_url='http://127.0.0.1:11434'):
    if plan.get('blocked_reason'):
        raise ValueError(plan['blocked_reason'])
    chosen = next((item for item in plan['options'] if item['id'] == model and item['eligible']), None) if model else plan['recommended']
    if not chosen:
        raise ValueError('This model does not fit the detected memory/disk plan. Refresh the hardware check or choose another model.')
    ram = plan['hardware'].get('memory', {}).get('total_gib') or 0
    gpu = max((item.get('memory_gib') or 0 for item in plan['hardware'].get('gpu', {}).get('devices', [])), default=0)
    context = 16384 if gpu >= 23 and ram >= 47 else 8192 if gpu >= 7 and ram >= 23 else 4096
    return {'provider': 'ollama', 'model': chosen['id'], 'base_url': base_url,
            'temperature': 0.0, 'timeout_seconds': 300, 'context_length': context,
            'max_output_tokens': min(2048, context // 4)}
