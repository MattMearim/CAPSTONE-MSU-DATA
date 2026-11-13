# FRIB workspace — Ayman version

Source-only publication of the local FRIB Decision Support workspace developed on the `ayman-version` branch. The application, tests, docs, sample inputs and private-runtime setup scripts are included. Installed runtimes, model weights, local evidence databases, caches and account-specific settings are intentionally downloaded or created locally.

## Start on Windows

Double-click **START_PROJECT.cmd**. First launch runs setup automatically: it installs the private Python runtime, application packages, portable Ollama, Qwen3 4B and MiniLM into **dependencies**, verifies the real models, then opens the workspace. First setup needs internet access and several gigabytes of storage. Later launches reuse the installation.

Use **STOP_PROJECT.cmd** to stop the workspace. **SETUP_PROJECT.cmd** reruns setup/repair. No global Python or Ollama installation is required.

For macOS, use `FRIB_Final_Project/START_FRIB.command`; its original source launcher uses the macOS managed storage layout described in the application docs.

## Included features

- Ollama / LM Studio model selection, saved profiles and compatibility checks.
- Hardware-aware main-model setup and optional adjustment after hardware upgrades.
- Model downloads by name/library link, role assignment and confirmed removal of unused models.
- A separately configurable, optional Data Quality Agent with read-only tools, bounded coverage, grounded graph flags and human-approved repairs into separate copies.
- Compact AI settings and chart-first event exploration with configurable views.
- Live CPU, RAM and GPU allocation information with a persistent hide/show switch.
- Original-file preservation, engineering analysis, approved-document retrieval, cited answers, draft review and a knowledge library.

The quality agent starts unassigned on a fresh clone. Open **AI settings → Quality agent → Get a small model** to download and enable Qwen3 1.7B, or choose another installed model.

## Source and workflow

- Application: [FRIB_Final_Project/FRIB_Decision_Support](FRIB_Final_Project/FRIB_Decision_Support)
- [Complete workflow](FRIB_Final_Project/FRIB_Decision_Support/docs/PRODUCT_WORKFLOW.md)
- [AI settings](FRIB_Final_Project/FRIB_Decision_Support/docs/AI_SETTINGS.md)
- [Data Quality Agent](FRIB_Final_Project/FRIB_Decision_Support/docs/DATA_QUALITY_AGENT.md)
- [Project audit and remaining limitations](PROJECT_CHECK_REPORT.md)

The latest focused interface/provider/quality suite passed 117 checks on Windows; earlier acceptance also exercised real local models, original preservation, restarts and protected model deletion. This is a local, single-user decision-support prototype. Existing audit findings and domain validation requirements are documented in the report; this branch does not claim production or facility commissioning.

## Development

After setup, install development tools from the source directory with the private Python interpreter and `pip install -e ".[ui,dev]"`. Tests use isolated storage and test doubles unless explicitly running a real-model verification script. Application source is preserved from the running workspace; this publication adds fresh-clone setup and sets the fallback chat model to Qwen3 4B. Saved user profiles and local datasets are excluded.
