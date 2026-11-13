"""Measure installed models with a short, fixed prompt; keep the app selection unchanged."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import requests

session = requests.Session()
session.trust_env = False
api = 'http://127.0.0.1:8000'
ollama = 'http://127.0.0.1:11434'
root = Path(__file__).resolve().parent

def get(path):
    response = session.get(api + path, timeout=90)
    response.raise_for_status()
    return response.json()

def generate(model):
    with requests.Session() as client:
        client.trust_env = False
        response = client.post(ollama + '/api/chat', json={'model': model, 'stream': False, 'think': False,
            'keep_alive': '10m', 'messages': [{'role': 'user', 'content': 'Explain in about 100 words why a document assistant should cite its sources.'}],
            'options': {'num_ctx': 4096, 'num_predict': 128, 'temperature': 0}}, timeout=(5, 600))
        response.raise_for_status()
        return response.json()

initial = get('/system/ai/resources')
active = initial['active']
results = []
with ThreadPoolExecutor(max_workers=1) as executor:
    for model in ['qwen3:8b', 'qwen3:4b']:
        print('Measuring ' + model, flush=True)
        future = executor.submit(generate, model)
        samples = []
        while not future.done():
            samples.append(get('/system/ai/resources'))
            time.sleep(2)
        response = future.result()
        time.sleep(2.1)
        samples.append(get('/system/ai/resources'))
        runtime = [item for sample in samples for item in sample['models'] if item['model'] == model and item['loaded']]
        duration = response.get('eval_duration', 0) / 1e9
        results.append({'model': model, 'context_tokens': 4096, 'max_output_tokens': 128,
            'output_tokens': response.get('eval_count'), 'generation_tokens_per_second': round(response.get('eval_count', 0) / duration, 2) if duration else None,
            'total_seconds': round(response.get('total_duration', 0) / 1e9, 2),
            'reported_loaded_model': runtime[-1] if runtime else None,
            'peak_ollama_resident_bytes_sampled': max((entry['resident_bytes'] for sample in samples for entry in sample['processes'] if entry['component'] == 'Ollama'), default=None),
            'peak_ollama_cpu_percent_sampled': max((entry['cpu_percent'] for sample in samples for entry in sample['processes'] if entry['component'] == 'Ollama'), default=None),
            'peak_gpu_utilization_sampled': max((entry['utilization_percent'] for sample in samples for entry in sample['gpu']['devices']), default=None),
            'samples': samples})
        print(json.dumps({key: value for key, value in results[-1].items() if key != 'samples'}), flush=True)
final = get('/system/ai/resources')
assert final['active'] == active, 'The measurement must not change the selected app model.'
report = {'measured_at': datetime.now(timezone.utc).isoformat(), 'initial': initial, 'results': results, 'final': final,
          'method': 'Sequential 128-token generation, 4096-token context, temperature zero, sampled about every two seconds. Sampled peaks are not guaranteed absolute peaks. RAM and model/GPU allocation overlap.'}
(root / 'logs/model-resource-comparison.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print('Saved model-resource-comparison.json; selected app model unchanged.', flush=True)
