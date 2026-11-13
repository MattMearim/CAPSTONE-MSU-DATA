"""Verify the selected local chat provider and unchanged semantic embeddings."""
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path

from run_frib import environment, selected_ai, start_bundled_ollama

dependencies = Path(__file__).resolve().parent
os.environ.update(environment())
selection = selected_ai()
if selection.provider == 'ollama' and selection.base_url == os.environ['FRIB_BUNDLED_OLLAMA_URL']:
    start_bundled_ollama()

from frib_ds.config import Config
from frib_ds.ai_settings import probe_model
from frib_ds.local_ai import check_embedding, validate_real_providers
from frib_ds.ai_storage import atomic_json

models = Config(create_dirs=False).models
validate_real_providers(models)
print(f'Checking chat and structured JSON: {selection.provider} / {selection.model}', flush=True)
probe = probe_model(selection)
print('Checking the unchanged semantic embedding model...', flush=True)
embedding = check_embedding(models)
receipt = {
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'llm': {'provider': selection.provider, 'model': selection.model, 'generation_verified': True,
            'structured_json_verified': True, 'sample': probe['sample']},
    'embedding': embedding,
    'dependencies': {name: importlib.metadata.version(name) for name in ('sentence-transformers', 'torch', 'transformers')},
    'mock_ai': False, 'hash_embeddings': False,
    'storage': {'ollama_models': os.environ['OLLAMA_MODELS'], 'embedding_cache': os.environ['FRIB_EMBEDDING_CACHE']},
}
atomic_json(dependencies / 'ai/real-ai-validation.json', receipt)
print(json.dumps(receipt, indent=2), flush=True)
print('Selected chat model and document-search model are ready.', flush=True)
