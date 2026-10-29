# Replacement guide

The project separates generation, processing, retrieval, storage and review behind small interfaces. Start the current application with **Start FRIB.cmd** or `python start.py`. Everyday data and file operations use the dashboard; provider configuration changes use YAML or process environment variables, followed by a restart. **Settings** shows connection status and audit activity; it does not edit configuration.

## Current defaults and alternatives

| Part | Default | Alternatives / interface | Main files |
|---|---|---|---|
| Response generation | `mock`: actual retrieved excerpts and deterministic drafts | Ollama or LM Studio; implement `LLMProvider.chat()` for another provider | `src/frib_ds/rag/llm.py`, `config/models.yaml` |
| Embeddings | `hash`: deterministic, lightweight search with limited relevance | SentenceTransformers; implement `EmbeddingProvider.embed()` | `src/frib_ds/rag/embeddings.py`, `config/models.yaml` |
| Vector index | Persistent SQLite | ChromaDB or hydrated memory; preserve `add`, `search` and `delete_document` behavior | `src/frib_ds/rag/vector_store.py` |
| Application records | SQLite | Preserve repository behavior, transactions and audit history | `src/frib_ds/storage/sqlite.py` |
| Original evidence and documents | Managed local files with checksums and catalog metadata | Preserve immutable bytes, ID-based lookup and confirmed deletion semantics | `src/frib_ds/storage/files.py`, `src/frib_ds/storage/documents.py` |
| Dashboard | Streamlit | Call the same FastAPI contracts and preserve the human review gate | `src/frib_ds/dashboard/app.py`, `src/frib_ds/api/main.py` |
| Domain processing | RF, mechanical and PLC processors | Implement `Processor.process()` and register the processor | `src/frib_ds/processing/` |
| Synthetic scenarios | YAML defaults plus dashboard overrides | Add or edit bounded, validated generator parameters | `config/scenarios/`, `src/frib_ds/generator/` |
| Retrieval and prompts | YAML retrieval settings and text prompts | Keep approved-source filtering, citation checks and evidence/interpretation labels | `config/rag.yaml`, `prompts/` |

## Enable optional local AI

1. Complete ordinary first-run setup with **Start FRIB.cmd**.
2. Copy **Active interpreter** from **System & upgrades → Hardware details**, then stop FRIB. In the project folder, replace the placeholder below with that exact path and install optional packages. A retained `.venv` may be inactive after an upgrade; refresh this path after further upgrades.

   ```powershell
   $fribPython = 'C:\paste\the\active\python.exe'
   & $fribPython -m pip install -e ".[rag]"
   ```

3. Install/run Ollama separately and make the configured model available. The default model name is in `config/models.yaml`; `FRIB_LLM_MODEL` can override it.
4. Run `& '.\Start FRIB.cmd' --local-ai` from PowerShell in the project folder.

The starter selects Ollama plus SentenceTransformers. Unless `FRIB_DATA_DIR` was explicitly supplied, this mode uses a separate `data-local-ai` directory. Reupload the required approved documents into that workspace. First-time semantic model loading can require internet access. Real-model answer quality still requires expert validation; a valid citation does not establish that an interpretation is true.

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

Restart with **Start FRIB.cmd** or `python start.py`. The `--local-ai` shortcut explicitly chooses Ollama; do not use that shortcut when testing the LM Studio configuration. Changing only the LLM does not change embedding definitions. Environment overrides take precedence over YAML, so remove a conflicting `FRIB_LLM_PROVIDER` override if necessary.

## Add a domain

1. Add a generator implementing `EventGenerator` and a processor implementing `Processor`.
2. Register both in their registries and add domain/scenario configuration.
3. Define expected signal names, units, discrete states and failure behavior.
4. Add meaningful numerical and contract tests, then update the dashboard labels and guides.

Preserving a dataset with an `other` domain does not create a new analysis capability automatically.

## Change retrieval behavior

Edit `config/rag.yaml` for retrieval count, relevance threshold and chunk settings; edit `prompts/rag_system.txt` for assistant behavior. Restart FRIB after configuration changes. Existing chunks are not automatically regenerated when chunking settings change: add a new document version or rebuild into a separate workspace deliberately. Uploaded documents are evidence, and instructions embedded in them must not override the application or human review requirements.

