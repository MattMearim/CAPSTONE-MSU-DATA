# Real local AI validation — October 30, 2026

The application now defaults to Ollama **qwen3:8b** for generated answers and SentenceTransformers **all-MiniLM-L6-v2** for semantic embeddings. SQLite stores the resulting vectors and application records. Both normal and presentation launchers select the real providers. Test doubles remain available to isolated automated tests.

## Installed and observed on this Mac

- Private Ollama runtime: **0.40.13**, official release archive verified against its published SHA-256 before extraction.
- Generation weights: **qwen3:8b**, downloaded and verified by Ollama. A real generation probe returned `READY`.
- Embedding weights: **all-MiniLM-L6-v2**, producing 384-dimensional vectors. Related pipe-leak descriptions scored 0.7612; the unrelated astronomy description scored 0.0447.
- Python: **3.12.1** in the validated private application environment.
- SentenceTransformers **6.2.0**, PyTorch **2.15.0**, Transformers **5.22.1**. `pip check` reported no broken requirements.
- Runtime/cache locations: `.frib/tools/ollama`, `.frib/models/ollama`, `.frib/cache/huggingface`, inside `FRIB_Decision_Support`.

## Application verification

The normal launcher started the API and dashboard on temporary test ports 8017 and 8517. Both health checks passed; the API reported `ollama`, `sentence_transformers` and `sqlite`. The migrated event appeared in the event list. The test instance was stopped after validation.

The original `data` workspace was preserved. Its one event, one procedure and three approved chunks were copied into `data-local-ai`; those chunks were recomputed with MiniLM. The copied catalog and vector index passed integrity/compatibility checks. `data-local-ai/SEMANTIC_MIGRATION.json` records this operation. Setup never overwrites an existing destination. Presentation data in the older `Demo_Workspace` is not migrated automatically.

The fictional Chernobyl dataset and procedure were imported into a separate temporary library. Analysis, semantic retrieval, real cited answer generation and AI knowledge-draft generation passed. The answer used three citations and stated that the simulated cause was unconfirmed and the event unresolved. The draft used a real model summary with explicitly labelled deterministic completion for missing fields and application-owned observations. Full observations are in `REAL_AI_VALIDATION.json`. The test library was removed after the run.

**Complete regression suite: 968 passed, 7 skipped.** Skips cover platform-dependent checks. This verifies the exercised software paths; it does not guarantee every future model answer. Generated guidance still requires source review and human judgment. Docker configuration was updated but a Docker runtime was not exercised on this Mac.

## Start or reinstall

Use outer **START_FRIB.command** for normal use, or **START_LIVE_DEMO.command** for fictional practice data. The launcher starts its private Ollama service when needed and cleans up a service it owns on shutdown. Existing user-managed Ollama servers are left running.

For a new computer or extracted download, double-click **START_FRIB.command**. It automatically prepares missing dependencies and models before starting the API and dashboard and opening the app; later launches reuse the installed environment and cached models. **SETUP_LOCAL_AI.command** remains optional for setup or repair without opening the app. Source archives include the installer and configuration; they exclude downloaded weights, private environments and saved records. First setup downloads the models on that computer and needs internet. `START_FRIB.command --check` verifies real model generation and embeddings; `start.py --check-packages` is the narrower dependency-only check used by packaging tests.
