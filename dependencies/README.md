# Private local runtime

Only setup, launcher and verification scripts are tracked in this folder. Run **START_PROJECT.cmd** at the repository root. If the runtime is absent it invokes setup automatically; **SETUP_PROJECT.cmd** explicitly reruns setup/repair.

First setup downloads and verifies:

- Private Python 3.13.16 from python.org, with a pinned archive checksum and publisher-signature check.
- Application packages from the declared Python requirements into `venv`.
- Portable Ollama 0.40.16 from its official GitHub release, with a pinned checksum and publisher-signature check.
- CPU MiniLM embeddings into `ai/cache/huggingface`.
- The configured main model (Qwen3 4B on a fresh clone) into `ai/models/ollama`.

The final real-model check creates `ai/real-ai-validation.json`, which the private launcher requires before serving the workspace. Failed setup stops with an error and can be retried; existing downloaded model weights are reused.

Generated runtimes, models, caches, logs and ownership receipts are ignored by Git. Application evidence lives separately in `FRIB_Final_Project/FRIB_Decision_Support/data-local-ai`, also ignored. Do not commit local model profiles, credentials or evidence databases.

Model changes and the optional independent quality agent are available in the application UI. See the root README and complete workflow guide. LM Studio manages its own runtime/model storage.

Windows virtual environments contain absolute paths. If moving an existing installed folder, recreate the private environment at its new location; a fresh Git clone naturally creates its own environment. Setup does not remove existing or incomplete runtime folders automatically.
