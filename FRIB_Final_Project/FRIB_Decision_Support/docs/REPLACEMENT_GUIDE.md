# Replacement guide

The project separates generation, processing, retrieval, storage and review behind small interfaces. Start the current application with **Start FRIB.cmd** or `python start.py`. Everyday data and file operations use the dashboard; provider configuration changes use YAML or process environment variables, followed by a restart. **Settings** shows connection status and audit activity; it does not edit configuration.

## Current defaults and alternatives

| Part | Default | Alternatives / interface | Main files |
|---|---|---|---|
| Response generation | Ollama `qwen3:8b` | Implement `LLMProvider.chat()` for another provider; mock is an isolated test double | `src/frib_ds/rag/llm.py`, `config/models.yaml` |
| Embeddings | SentenceTransformers `all-MiniLM-L6-v2` | Implement `EmbeddingProvider.embed()`; hash is an isolated test double | `src/frib_ds/rag/embeddings.py`, `config/models.yaml` |
| Vector index | Persistent SQLite | ChromaDB or hydrated memory; preserve `add`, `search` and `delete_document` behavior | `src/frib_ds/rag/vector_store.py` |
| Application records | SQLite | Preserve repository behavior, transactions and audit history | `src/frib_ds/storage/sqlite.py` |
| Original evidence and documents | Managed local files with checksums and catalog metadata | Preserve immutable bytes, ID-based lookup and confirmed deletion semantics | `src/frib_ds/storage/files.py`, `src/frib_ds/storage/documents.py` |
| Dashboard | Streamlit | Call the same FastAPI contracts and preserve the human review gate | `src/frib_ds/dashboard/app.py`, `src/frib_ds/api/main.py` |
| Domain processing | RF, mechanical and PLC processors | Implement `Processor.process()` and register the processor | `src/frib_ds/processing/` |
| Synthetic scenarios | YAML defaults plus dashboard overrides | Add or edit bounded, validated generator parameters | `config/scenarios/`, `src/frib_ds/generator/` |
| Retrieval and prompts | YAML retrieval settings and text prompts | Keep approved-source filtering, citation checks and evidence/interpretation labels | `config/rag.yaml`, `prompts/` |

## Prepare the required local AI

On macOS, double-click the outer **START_FRIB.command**, or **Start FRIB.command** inside the source folder. It automatically prepares missing application dependencies, the private Ollama runtime, qwen3:8b and the all-MiniLM-L6-v2 cache, then starts the services and opens the app. **SETUP_LOCAL_AI.command** is optional for setup or repair. The private runtime is under `.frib/tools`, model weights under `.frib/models/ollama` and embedding cache under `.frib/cache/huggingface`.

On Windows, make Ollama and qwen3:8b available; the launcher prepares the Python dependencies. Start with **Start FRIB.cmd**. All normal application runs use real AI and `data-local-ai` unless you explicitly select another `FRIB_DATA_DIR`. If `data/frib.db` exists and `data-local-ai` does not, first setup copies the normal workspace and re-embeds approved chunks. The source is untouched and an existing destination is never overwritten. The presentation uses `Demo_Workspace_AI`; the older `Demo_Workspace` is retained but not migrated automatically. Upload presentation procedures there when needed. First setup needs internet and model storage. Model errors are reported, with no silent fallback to mock answers or hash embeddings. Real-model answer quality still requires expert validation; a valid citation does not establish that an interpretation is true.

### Keep embedding indexes compatible

The repository records an embedding fingerprint. When approved document chunks exist, startup rejects a different or unknown fingerprint instead of silently mixing vectors. The fingerprint includes the provider and relevant model, dimensions or tokenizer version.

To change embeddings, stop FRIB, select a separate `FRIB_DATA_DIR`, restart with the intended provider/model, then reupload original documents. Keep the old data directory as a backup. Do not edit or delete compatibility metadata to force incompatible vectors to load.

## Use LM Studio

Start an LM Studio local server with the desired model and edit the LLM section in `config/models.yaml`:

```yaml
llm:
  provider: lmstudio
  model: your-loaded-model-id
  lmstudio_base_url: http://localhost:1234/v1
```

This is an advanced alternative provider, separate from the required Ollama setup. The ordinary `--local-ai` entrypoints explicitly select Ollama. To test LM Studio, use the provider-aware Python entrypoint and confirm the effective provider in system status before querying. Changing only the LLM does not change embedding definitions. Environment overrides take precedence over YAML, so remove a conflicting `FRIB_LLM_PROVIDER` override if necessary.

## Add a domain

1. Add a generator implementing `EventGenerator` and a processor implementing `Processor`.
2. Register both in their registries and add domain/scenario configuration.
3. Define expected signal names, units, discrete states and failure behavior.
4. Add meaningful numerical and contract tests, then update the dashboard labels and guides.

Preserving a dataset with an `other` domain does not create a new analysis capability automatically.

## Change retrieval behavior

Edit `config/rag.yaml` for retrieval count, relevance threshold and chunk settings; edit `prompts/rag_system.txt` for assistant behavior. Restart FRIB after configuration changes. Existing chunks are not automatically regenerated when chunking settings change: add a new document version or rebuild into a separate workspace deliberately. Uploaded documents are evidence, and instructions embedded in them must not override the application or human review requirements.

