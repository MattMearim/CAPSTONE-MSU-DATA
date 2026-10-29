# Startup, system information and upgrades

## Start from one shortcut

Extract the complete project ZIP into a writable folder, then double-click **Start FRIB.cmd**. The outer **START_FRIB.cmd** shortcut opens the same launcher. Keep its console window open while using the dashboard; press **Ctrl+C** in that window to stop both services.

The Windows launcher detects a supported 64-bit Python 3.11–3.13, checks the required application packages, their minimum versions and imports, and verifies dependency consistency. Missing or damaged environments are rebuilt automatically. A healthy installation can start without contacting a package index. The dashboard opens after both services report ready.

If Python is unavailable, the launcher downloads the official full Python 3.13.16 managed-runtime archive from python.org. It verifies the fixed SHA-256 checksum and the Python Software Foundation signature on the extracted executable. This is a private runtime under `.frib/python`, with no system Python replacement, PATH change or administrator installation. An interrupted download or failed check produces an explanation; unverified executables do not run.

Automatic runtime bootstrap and queued runtime upgrades support Windows x64 and ARM64. ARM64 dependency availability depends on compatible published wheels and has not been tested on physical ARM hardware. The application has been validated on Windows 11 x64. On other operating systems, install a suitable Python yourself and run `python start.py`.

First setup, repairs requiring downloads and requested updates need internet access, a writable project directory and sufficient free disk space. Organization policies may block downloads or local scripts. The launcher cannot override those policies. Avoid moving a configured project: Python environments contain absolute paths. Extract a fresh source copy and copy backed-up data/configuration after stopping FRIB instead.

## System & upgrades

The sidebar page has three focused views:

- **Required software:** installed versions, purpose, local status and individual update choices for the scientific libraries, API, dashboard, PDF support, Python and pip. Search for a component or show all cards. SQLite is bundled with Python.
- **Optional AI:** resource estimates and semantic-search dependencies. Model runtimes and model downloads are separate explicit choices. The default mock/hash/SQLite mode works without them.
- **Startup plan:** queued changes, cancellation and the recorded result of the last update.

Hardware details include CPU, RAM, free project-drive space and GPU information when available. Unknown measurements stay unknown. Resource tiers are planning estimates, not benchmarks or guarantees. Optional semantic dependencies currently require a confirmed 64-bit machine, at least 15 GiB reported RAM (16 GB class) and 8 GiB free disk to enable the curated choice. Local-model guidance also considers disk and reported GPU memory.

**Refresh hardware & software** reads local information. **Check latest versions** explicitly requests public package metadata from PyPI; it sends package names, not uploaded evidence or procedures. A latest release label does not establish application compatibility. The installer resolves releases that match Python, the platform and dependency constraints. Offline version checks can fail while installed software remains usable.

## Apply an upgrade

1. Expand a component's **Version details and update options**, then select its update choice. Choose **Queue selected updates**, or choose **Queue required updates** for the complete required package set.
2. Review **Startup plan**. Queueing another plan replaces the previous plan; cancel it here if needed.
3. Stop FRIB with **Ctrl+C** in its launcher window.
4. Double-click **Start FRIB.cmd** again. The launcher applies the selected plan before opening the dashboard.

Updates run in a separate versioned environment under `.frib/environments`. Installed optional and development dependencies are retained when rebuilding an existing usable environment. Dependency resolution, required imports, optional imports when present, and `pip check` must succeed before the active-environment pointer changes. The previous environment remains on disk. The queue never accepts arbitrary package names, shell commands or download URLs.

Package updates can also update compatible transitive dependencies. Validation reduces upgrade risk but does not replace the full application test suite. The current source code is reinstalled from this project; package updates do not download a new FRIB source release. Python's standard libraries, including SQLite, update with the runtime. Provider selections, configuration, uploads, datasets, procedures and reviewed knowledge are separate from environment maintenance.

If a queued update fails and the previous environment passed validation, FRIB starts that working environment. The failed result and pending plan remain visible in **System & upgrades → Startup plan**, where you can cancel the plan or correct the reported cause before restarting to retry it. First installation or repair still stops if no healthy previous environment is available. Do not delete the `data` or `data-local-ai` folders as an installation repair. Back up those folders while FRIB is stopped.

## Verify setup and application behavior

Run **Start FRIB.cmd --check** from a terminal for installation validation without starting the two services. Double-click **Run Test Lab.cmd** for automatic setup followed by 32 grouped API checks using disposable storage. It creates `test_lab_results/TEST_LAB_RESULTS.md` and JSON evidence without resetting your saved workspace.

Developers can run the complete pytest suite, `scripts/run_system_smoke.py` and the L1/L2 presentation runner with the active environment's Python. The current interpreter path is visible in the system report. A legacy `.venv` may still be retained after an upgrade, so use the active path rather than assuming `.venv` is current.

## Official sources

Runtime selection and bootstrap were checked against [Python 3.13.16](https://www.python.org/downloads/release/python-31316/), its [Windows runtime manifest](https://www.python.org/ftp/python/3.13.16/windows-3.13.16.json), and [Python's Windows documentation](https://docs.python.org/3.13/using/windows.html) on October 12, 2026. Package installation uses the [pip resolver](https://pip.pypa.io/en/stable/cli/pip_install/) and public PyPI metadata. Optional runtime guidance comes from [Ollama's Windows requirements](https://docs.ollama.com/windows); local-model behavior still needs validation on the intended machine.
