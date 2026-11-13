# Working code and Finder guide

The active application is the **FRIB_Final_Project 100** copy in Michigan State University OneDrive. Its application code is inside **FRIB_Decision_Support**. The latest reviewed files are in this downloadable release and the workspace copy below. The earlier OneDrive installation may differ; extract this release and use its FRIB_Decision_Support folder for the latest code.

## Find the active project

In Finder, press **Command + Shift + G**, paste this path, and press Return:

```text
/Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100
```

Open **FRIB_Decision_Support** to see the application, tests and configuration. Use **START_FRIB.command** in the outer folder to start the normal app. **START_LIVE_DEMO.command** starts the synthetic demo workflow; **RUN_DEMO_CHECKS.command** checks the demo.

- Active application folder: [FRIB_Decision_Support](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support>)
- Active source code: [src/frib_ds](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds>)
- Active automated tests: [tests](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests>)
- Tested workspace copy: [FRIB_Final_Project/FRIB_Decision_Support](</Users/hitheshnannapaneni/Documents/ChatGPT/Wuva 1/FRIB_Final_Project/FRIB_Decision_Support>)

Folders named **FRIB_Final_Project 2**, **FRIB_Final_Project 3**, **FRIB_Final_Project CURRENT3**, and the original **Downloads/FRIB_Final_Project** are older or separate copies. They are not the target of this code inventory or the final synchronization.

## Where the important pieces live

| Area | Active location | Purpose |
| --- | --- | --- |
| macOS launchers | [START_FRIB.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/START_FRIB.command>) and [Start FRIB.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Start FRIB.command>) | Start the app and choose/repair its managed Python environment. |
| Startup and process management | [start.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/start.py>), [launcher.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/launcher.py>) | Readiness checks, app lifecycle and browser opening. |
| User interface and tutorial | [src/frib_ds/dashboard](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard>) | Screens, navigation, visual styling, onboarding and data-quality review. |
| API and browser request boundary | [src/frib_ds/api](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/api>) | Endpoints, validation, upload limits and local browser protections. |
| Data import and quality checks | [ingestion](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion>) and [quality](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/quality>) | Read uploads, report quality problems and preserve explicit repair choices. |
| Engineering calculations | [processing](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing>) and [units.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/units.py>) | Derive RF, mechanical and PLC observations; convert compatible units. |
| Synthetic data | [src/frib_ds/generator](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator>) | Reproducible fictional datasets for training and testing. |
| Document retrieval and models | [src/frib_ds/rag](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag>) | Parse documents, create/search embeddings and connect configured model providers. |
| Knowledge and human review | [src/frib_ds/knowledge](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/knowledge>) | Evidence-linked drafts, tentative hypotheses and explicit review decisions. |
| Persistence and reset | [src/frib_ds/storage](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage>) | Original files, SQLite records, review transactions, deletion and reset locking. |
| Configuration | [config](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config>), [prompts](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/prompts>), [pyproject.toml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/pyproject.toml>) | App/provider settings, model instructions and declared dependencies. |
| Tests and maintenance | [tests](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests>) and [scripts](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts>) | Unit/regression checks, demo checks, packaging and schema export. |

## Run the tests

The **tests** folder contains the unit and regression tests; these are separate from the interactive **Run Test Lab.command** demonstration. The test suite uses temporary directories and test clients to exercise uploads, review decisions, retrieval, resets, startup, packaging and the user interface.

- Double-click [RUN_UNIT_TESTS.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_UNIT_TESTS.command>) in the outer folder, or [Run Unit Tests.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Unit Tests.command>) inside the application folder.
- For dependency and static security scans, double-click [RUN_SECURITY_CHECKS.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_SECURITY_CHECKS.command>) or [Run Security Checks.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Security Checks.command>). The first scan may install its scanner tools into **.frib/security-tools**, separate from system Python.
- Windows has corresponding **.cmd** wrappers with the same names.

For a terminal run from **FRIB_Decision_Support**, the helper selects the project's active Python environment:

```sh
python3 scripts/run_tests.py
python3 scripts/run_tests.py --security --install-tools
```

Reports are written to **.frib/test-reports**. A fresh machine needs the project setup/development dependencies before it can run the full test suite. [.github/workflows/checks.yml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.github/workflows/checks.yml>) provides the repeatable automated checks when the project is placed in a GitHub repository.

The new adversarial cases are in [test_security_api.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_api.py>), [test_security_uploads.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_uploads.py>), [test_security_runtime.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_runtime.py>) and [test_security_integrity.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_integrity.py>). They cover bounded requests, hostile uploads, launcher boundaries, review races, database input and stale document retrieval. Passing tests describe the behaviors checked; they do not prove an absence of vulnerabilities or validate every external model response.

## Full working-file inventory

This snapshot lists **162 authored code, test and configuration files**. It excludes virtual environments, installed dependency metadata, caches, uploaded data, generated reports and older copies. Sample captures and procedures remain in **sample_data**, **sample_docs** and the outer **Live_Demo_Data** folder; they are fixtures rather than executable application code.

[CODE_FILES.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/docs/CODE_FILES.json>) contains every path below, byte size and SHA-256 fingerprint for comparing the final copy. Fingerprints identify file contents; they are not a security guarantee.

| Group | Files |
| --- | ---: |
| Application source | 58 |
| Unit and regression tests | 43 |
| Support and verification scripts | 18 |
| Application launchers and test entry points | 7 |
| Configuration and build files | 20 |
| Prompt templates | 3 |
| Schema contracts | 5 |
| Bundle launchers | 8 |

### Application source

- [src/frib_ds/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/__init__.py>)
- [src/frib_ds/api/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/api/__init__.py>)
- [src/frib_ds/api/main.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/api/main.py>)
- [src/frib_ds/api/security.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/api/security.py>)
- [src/frib_ds/bootstrap.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/bootstrap.py>)
- [src/frib_ds/config.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/config.py>)
- [src/frib_ds/dashboard/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/__init__.py>)
- [src/frib_ds/dashboard/app.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/app.py>)
- [src/frib_ds/dashboard/design.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/design.py>)
- [src/frib_ds/dashboard/event_view.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/event_view.py>)
- [src/frib_ds/dashboard/ingestion_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/ingestion_ui.py>)
- [src/frib_ds/dashboard/quality_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/quality_ui.py>)
- [src/frib_ds/dashboard/reset_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/reset_ui.py>)
- [src/frib_ds/dashboard/system_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/system_ui.py>)
- [src/frib_ds/dashboard/test_lab_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/test_lab_ui.py>)
- [src/frib_ds/dashboard/tutorial_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/tutorial_ui.py>)
- [src/frib_ds/dashboard/workbench.css](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/dashboard/workbench.css>)
- [src/frib_ds/generator/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/__init__.py>)
- [src/frib_ds/generator/base.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/base.py>)
- [src/frib_ds/generator/mechanical.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/mechanical.py>)
- [src/frib_ds/generator/plc.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/plc.py>)
- [src/frib_ds/generator/registry.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/registry.py>)
- [src/frib_ds/generator/rf.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/generator/rf.py>)
- [src/frib_ds/ingestion/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/__init__.py>)
- [src/frib_ds/ingestion/common.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/common.py>)
- [src/frib_ds/ingestion/narrative.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/narrative.py>)
- [src/frib_ds/ingestion/quality.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/quality.py>)
- [src/frib_ds/ingestion/service.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/service.py>)
- [src/frib_ds/ingestion/tabular.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/ingestion/tabular.py>)
- [src/frib_ds/knowledge/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/knowledge/__init__.py>)
- [src/frib_ds/knowledge/hypotheses.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/knowledge/hypotheses.py>)
- [src/frib_ds/knowledge/service.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/knowledge/service.py>)
- [src/frib_ds/launcher.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/launcher.py>)
- [src/frib_ds/models.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/models.py>)
- [src/frib_ds/processing/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/__init__.py>)
- [src/frib_ds/processing/base.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/base.py>)
- [src/frib_ds/processing/common.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/common.py>)
- [src/frib_ds/processing/evidence.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/evidence.py>)
- [src/frib_ds/processing/mechanical.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/mechanical.py>)
- [src/frib_ds/processing/plc.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/plc.py>)
- [src/frib_ds/processing/registry.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/registry.py>)
- [src/frib_ds/processing/rf.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/processing/rf.py>)
- [src/frib_ds/quality/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/quality/__init__.py>)
- [src/frib_ds/quality/common.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/quality/common.py>)
- [src/frib_ds/quality/event_checks.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/quality/event_checks.py>)
- [src/frib_ds/rag/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/__init__.py>)
- [src/frib_ds/rag/document_loader.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/document_loader.py>)
- [src/frib_ds/rag/embeddings.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/embeddings.py>)
- [src/frib_ds/rag/llm.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/llm.py>)
- [src/frib_ds/rag/service.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/service.py>)
- [src/frib_ds/rag/vector_store.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/rag/vector_store.py>)
- [src/frib_ds/storage/__init__.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage/__init__.py>)
- [src/frib_ds/storage/documents.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage/documents.py>)
- [src/frib_ds/storage/files.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage/files.py>)
- [src/frib_ds/storage/reset.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage/reset.py>)
- [src/frib_ds/storage/sqlite.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/storage/sqlite.py>)
- [src/frib_ds/system_manager.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/system_manager.py>)
- [src/frib_ds/units.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/src/frib_ds/units.py>)

### Unit and regression tests

- [tests/test_api_lifecycle.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_api_lifecycle.py>)
- [tests/test_backend_regressions.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_backend_regressions.py>)
- [tests/test_chunk_configuration.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_chunk_configuration.py>)
- [tests/test_dashboard_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_dashboard_ui.py>)
- [tests/test_distribution.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_distribution.py>)
- [tests/test_draft_hypotheses.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_draft_hypotheses.py>)
- [tests/test_event_quality.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_event_quality.py>)
- [tests/test_evidence_processing.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_evidence_processing.py>)
- [tests/test_generators.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_generators.py>)
- [tests/test_hypotheses.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_hypotheses.py>)
- [tests/test_ingestion.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_ingestion.py>)
- [tests/test_integrity.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_integrity.py>)
- [tests/test_launcher_reopen.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_launcher_reopen.py>)
- [tests/test_macos_packaging.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_macos_packaging.py>)
- [tests/test_mixed_api.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_mixed_api.py>)
- [tests/test_plot_presentation.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_plot_presentation.py>)
- [tests/test_preview_limits.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_preview_limits.py>)
- [tests/test_processing.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_processing.py>)
- [tests/test_processing_robustness.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_processing_robustness.py>)
- [tests/test_quality_api.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_quality_api.py>)
- [tests/test_quality_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_quality_ui.py>)
- [tests/test_rag_lightweight.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_rag_lightweight.py>)
- [tests/test_rag_service.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_rag_service.py>)
- [tests/test_reset.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_reset.py>)
- [tests/test_reset_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_reset_ui.py>)
- [tests/test_review_gate.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_review_gate.py>)
- [tests/test_security_api.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_api.py>)
- [tests/test_security_integrity.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_integrity.py>)
- [tests/test_security_runtime.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_runtime.py>)
- [tests/test_security_uploads.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_security_uploads.py>)
- [tests/test_showcase_distribution.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_showcase_distribution.py>)
- [tests/test_simple_evidence_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_simple_evidence_ui.py>)
- [tests/test_simple_workspace_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_simple_workspace_ui.py>)
- [tests/test_startup.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_startup.py>)
- [tests/test_system_manager.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_system_manager.py>)
- [tests/test_system_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_system_ui.py>)
- [tests/test_test_lab.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_test_lab.py>)
- [tests/test_tsv_ingestion.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_tsv_ingestion.py>)
- [tests/test_tutorial_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_tutorial_ui.py>)
- [tests/test_units.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_units.py>)
- [tests/test_upload_quality.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_upload_quality.py>)
- [tests/test_wiki_home_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_wiki_home_ui.py>)
- [tests/test_workbench_ui.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/tests/test_workbench_ui.py>)

### Support and verification scripts

- [scripts/bootstrap_windows.ps1](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/bootstrap_windows.ps1>)
- [scripts/build_l1_l2_showcase.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/build_l1_l2_showcase.py>)
- [scripts/export_l1_l2_slide_evidence.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/export_l1_l2_slide_evidence.py>)
- [scripts/export_openapi.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/export_openapi.py>)
- [scripts/export_schemas.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/export_schemas.py>)
- [scripts/generate_event.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/generate_event.py>)
- [scripts/generate_test_lab.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/generate_test_lab.py>)
- [scripts/index_document.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/index_document.py>)
- [scripts/l1_l2_demo_generators.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/l1_l2_demo_generators.py>)
- [scripts/package_final_bundle.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/package_final_bundle.py>)
- [scripts/package_project.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/package_project.py>)
- [scripts/run_checks.sh](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/run_checks.sh>)
- [scripts/run_l1_l2_demo.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/run_l1_l2_demo.py>)
- [scripts/run_system_smoke.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/run_system_smoke.py>)
- [scripts/run_test_lab.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/run_test_lab.py>)
- [scripts/run_tests.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/run_tests.py>)
- [scripts/seed_demo.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/seed_demo.py>)
- [scripts/start_unix.sh](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/scripts/start_unix.sh>)

### Application launchers and test entry points

- [Run Security Checks.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Security Checks.command>)
- [Run Test Lab.cmd](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Test Lab.cmd>)
- [Run Test Lab.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Test Lab.command>)
- [Run Unit Tests.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Run Unit Tests.command>)
- [Start FRIB.cmd](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Start FRIB.cmd>)
- [Start FRIB.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Start FRIB.command>)
- [start.py](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/start.py>)

### Configuration and build files

- [.dockerignore](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.dockerignore>)
- [.env.demo](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.env.demo>)
- [.env.example](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.env.example>)
- [.github/workflows/checks.yml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.github/workflows/checks.yml>)
- [.gitignore](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.gitignore>)
- [.streamlit/config.toml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/.streamlit/config.toml>)
- [config/app.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/app.yaml>)
- [config/domains.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/domains.yaml>)
- [config/models.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/models.yaml>)
- [config/processing.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/processing.yaml>)
- [config/rag.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/rag.yaml>)
- [config/scenarios/mechanical_vibration.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/scenarios/mechanical_vibration.yaml>)
- [config/scenarios/plc_interlock.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/scenarios/plc_interlock.yaml>)
- [config/scenarios/rf_cavity_trip.yaml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/config/scenarios/rf_cavity_trip.yaml>)
- [docker-compose.yml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/docker-compose.yml>)
- [Dockerfile.backend](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Dockerfile.backend>)
- [Dockerfile.dashboard](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Dockerfile.dashboard>)
- [Makefile](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/Makefile>)
- [pyproject.toml](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/pyproject.toml>)
- [requirements-tested.txt](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/requirements-tested.txt>)

### Prompt templates

- [prompts/knowledge_system.txt](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/prompts/knowledge_system.txt>)
- [prompts/rag_system.txt](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/prompts/rag_system.txt>)
- [prompts/rag_user.txt](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/prompts/rag_user.txt>)

### Schema contracts

- [contracts/analysis.schema.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/contracts/analysis.schema.json>)
- [contracts/event.schema.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/contracts/event.schema.json>)
- [contracts/knowledge.schema.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/contracts/knowledge.schema.json>)
- [contracts/rag.schema.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/contracts/rag.schema.json>)
- [contracts/review.schema.json](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/FRIB_Decision_Support/contracts/review.schema.json>)

### Bundle launchers

- [../RUN_DEMO_CHECKS.cmd](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_DEMO_CHECKS.cmd>)
- [../RUN_DEMO_CHECKS.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_DEMO_CHECKS.command>)
- [../RUN_SECURITY_CHECKS.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_SECURITY_CHECKS.command>)
- [../RUN_UNIT_TESTS.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/RUN_UNIT_TESTS.command>)
- [../START_FRIB.cmd](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/START_FRIB.cmd>)
- [../START_FRIB.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/START_FRIB.command>)
- [../START_LIVE_DEMO.cmd](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/START_LIVE_DEMO.cmd>)
- [../START_LIVE_DEMO.command](</Users/hitheshnannapaneni/Library/CloudStorage/OneDrive-MichiganStateUniversity/FRIB_Final_Project 100/START_LIVE_DEMO.command>)

Application files remain ordinary editable source files. Keep runtime folders such as **.frib** and **data** separate from code-only copies: **.frib** contains the managed environment and process state, while **data** contains application records and uploaded originals.
