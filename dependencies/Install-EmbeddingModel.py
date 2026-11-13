"""Install the required MiniLM assets into the project's dependencies directory."""
from pathlib import Path
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

DEPENDENCIES = Path(__file__).resolve().parent
CACHE = DEPENDENCIES / 'ai' / 'cache' / 'huggingface'
HUB = CACHE / 'hub'
TEMP = DEPENDENCIES / 'tmp' / 'embedding-install'
for directory in (CACHE, HUB, TEMP, DEPENDENCIES / 'logs'):
    directory.mkdir(parents=True, exist_ok=True)
os.environ.update({
    'HF_HOME': str(CACHE),
    'HF_HUB_CACHE': str(HUB),
    'HUGGINGFACE_HUB_CACHE': str(HUB),
    'FRIB_EMBEDDING_CACHE': str(HUB),
    'SENTENCE_TRANSFORMERS_HOME': str(HUB),
    'HF_XET_CACHE': str(CACHE / 'xet'),
    'HF_MODULES_CACHE': str(CACHE / 'modules'),
    'HF_DATASETS_CACHE': str(CACHE / 'datasets'),
    'TORCH_HOME': str(DEPENDENCIES / 'ai' / 'cache' / 'torch'),
    'XDG_CACHE_HOME': str(DEPENDENCIES / 'ai' / 'cache'),
    'HF_HUB_DISABLE_TELEMETRY': '1',
    'HF_HUB_DISABLE_PROGRESS_BARS': '1',
    'HF_HUB_DISABLE_SYMLINKS_WARNING': '1',
    'HF_HUB_DISABLE_XET': '1',
    'HF_HUB_OFFLINE': '0',
    'TEMP': str(TEMP),
    'TMP': str(TEMP),
})

from huggingface_hub import HfApi, snapshot_download

identifier = 'sentence-transformers/all-MiniLM-L6-v2'
print(f'Inspecting the official {identifier} repository.', flush=True)
info = HfApi().model_info(identifier)
revision = info.sha
allowed = [
    'model.safetensors', 'config.json', 'config_sentence_transformers.json',
    'modules.json', 'sentence_bert_config.json', 'tokenizer.json',
    'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt',
    '1_Pooling/config.json', 'README.md', 'LICENSE', 'LICENSE.txt',
]
print(f'Downloading the required safetensors/tokenizer assets at revision {revision}.', flush=True)
snapshot = Path(snapshot_download(identifier, revision=revision, cache_dir=str(HUB),
                                  allow_patterns=allowed, max_workers=3))
required = ['model.safetensors', 'config.json', 'modules.json', '1_Pooling/config.json',
            'tokenizer.json', 'tokenizer_config.json', 'vocab.txt']
missing = [name for name in required if not (snapshot / name).is_file()]
if missing:
    raise RuntimeError(f'Missing required embedding assets: {missing}')
# A commit-pinned download does not necessarily create the name's main ref.
# Set it to this exact official commit so short-name offline loads reuse it.
ref = HUB / 'models--sentence-transformers--all-MiniLM-L6-v2' / 'refs' / 'main'
ref.parent.mkdir(parents=True, exist_ok=True)
ref.write_text(revision, encoding='utf-8')

print('Loading MiniLM on CPU and checking real semantic vectors.', flush=True)
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(identifier, device='cpu', cache_folder=str(HUB),
                            local_files_only=True, revision=revision)
sentences = ['A leaking pipe releases water.', 'Water escapes from a damaged pipe.',
             'The telescope observes a distant galaxy.']
vectors = model.encode(sentences, normalize_embeddings=True, show_progress_bar=False)
assert vectors.shape == (3, 384), vectors.shape
assert all(math.isfinite(float(value)) for vector in vectors for value in vector)
related = float(vectors[0] @ vectors[1])
unrelated = float(vectors[0] @ vectors[2])
assert related > unrelated, (related, unrelated)
files = []
for path in sorted(snapshot.rglob('*')):
    if path.is_file():
        files.append({'name': str(path.relative_to(snapshot)).replace('\\', '/'),
                      'size_bytes': path.stat().st_size,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
receipt = {
    'component': 'semantic-embedding-model', 'installed_at_utc': datetime.now(timezone.utc).isoformat(),
    'repository': identifier, 'revision': revision, 'source': f'https://huggingface.co/{identifier}',
    'cache_folder': str(HUB), 'snapshot': str(snapshot), 'device': 'cpu',
    'vector_shape': list(vectors.shape), 'similarity_related': related,
    'similarity_unrelated': unrelated, 'model_load_local_only': True,
    'download_utility_python': sys.executable, 'files': files,
}
(DEPENDENCIES / 'embedding-installation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in receipt.items() if key != 'files'}, indent=2), flush=True)
