# FRIB — one-click Windows edition

This is the lightweight system folder. It contains application code, sample inputs, documentation and setup scripts. It contains no installed Python, application packages, AI engines, model weights or saved user databases.

## Run

1. Extract the complete ZIP into a writable folder on your Windows computer.
2. Double-click **START_PROJECT.bat**.
3. Keep its window open during first setup. The browser opens automatically when the workspace is ready.

The first launch creates **dependencies** beside the batch file and installs private Python, the pinned application packages, portable Ollama, Qwen3 4B and MiniLM embeddings there. It verifies the real models before starting the application. Internet access and several gigabytes of free storage are needed for first setup. No existing Python or Ollama installation is required, and setup does not change the system PATH.

Later launches reuse the installation. Double-click **STOP_PROJECT.bat** to stop the workspace. Failed setup can be retried by opening START_PROJECT.bat again; cached downloads and saved data are retained. The setup log is `dependencies/logs/setup.log`.

## Locations

- `FRIB_Final_Project/FRIB_Decision_Support`: application, docs and examples.
- `setup`: the small first-run bootstrap scripts and package-version constraints.
- `dependencies`: created on first launch; all installed tools, packages, AI assets and caches go here.
- `FRIB_Final_Project/FRIB_Decision_Support/data-local-ai`: your saved workspace, created when the app runs.

The app opens at http://127.0.0.1:8501. Keep the installed folder in the same location; Windows virtual environments contain absolute paths. To distribute a clean copy, share this original ZIP rather than a folder that already contains dependencies or saved data.

## AI and workflow

Use **AI settings** to change the main model, add or remove models, enable hardware matching or configure the separate optional Data Quality Agent. On a clean install, enable the quality agent through **Quality agent → Get a small model**. All model downloads stay in dependencies. LM Studio remains an optional externally managed engine.

[Complete workflow](FRIB_Final_Project/FRIB_Decision_Support/docs/PRODUCT_WORKFLOW.md) · [AI settings](FRIB_Final_Project/FRIB_Decision_Support/docs/AI_SETTINGS.md) · [Quality agent](FRIB_Final_Project/FRIB_Decision_Support/docs/DATA_QUALITY_AGENT.md)

This package targets 64-bit Windows. The existing source launchers and documents for other platforms remain inside the application folder. The project audit documents remaining prototype and domain-validation limitations.
