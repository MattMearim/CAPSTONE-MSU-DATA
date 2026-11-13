# One active FRIB workspace: the latest launch has priority

A normal application launch keeps one active FRIB workspace for your user across project copies. Open the launcher in the project you want to use. The most recently opened normal launcher has priority, safely stops the older FRIB workers, and starts the selected project. This includes starting the same copy again, switching to a newer extracted copy, or switching between the normal and presentation launchers.

## Open the project you want

1. Extract the complete project, if it is a new copy.
2. Open **START_FRIB.command** on macOS or **START_FRIB.cmd** on Windows. Use **START_LIVE_DEMO** for that copy's presentation workspace. Inner **Start FRIB** launchers use the same policy.
3. Let the newest startup window finish the handoff and setup. It starts the backend and dashboard together and opens the selected project when ready.
4. Keep that newest window open while working. **Stop workspace** stops its workspace when you are finished. A terminal-only launch supports **Ctrl+C** for a manual stop.

You do not have to locate an older launcher or press Ctrl+C before an ordinary restart or copy switch. The newer startup has priority over an earlier startup that is still preparing the app, as well as over an app that is already running. An earlier superseded startup stops rather than launching another workspace later.

The app does not silently select alternate ports to keep both FRIB copies running. Explicit port options remain configuration options for the selected workspace; they do not create an exception to the one-active-workspace policy.

## Your saved records and installed models stay on disk

The handoff stops FRIB processes. It does not delete databases, uploaded files, procedures, reviewed knowledge, model weights or installed dependencies. The selected project opens its own configured saved-data directory, such as its `FRIB_Decision_Support/data-local-ai` or outer `Demo_Workspace_AI`. Switching copies does not merge records from those directories or overwrite the older copy's data.

On macOS, installed AI models and tools remain in the shared permanent **~/Library/Application Support/FRIB** folder, or the configured **FRIB_AI_HOME**. An already installed compatible model is reused. Moving to a fresh project copy does not require downloading those same model weights again.

Save form changes and finish any work you want to keep before opening another copy. Unsaved browser form state or an in-flight generation is not a saved record and may not finish during a handoff.

## Updates are applied after the handoff

If the selected project has a queued update plan, its normal startup first stops the older FRIB workers, then prepares and validates the replacement environment. This prevents the old app from holding the environment that startup needs to update. Existing rollback, dependency and import checks remain in place. Opening another copy does not copy an update plan from the older project into the new one.

## Maintenance commands do not replace the running app

**--check**, **--check-packages**, **--setup-local-ai**, **--test-lab** and help commands keep their maintenance behavior. They do not claim normal-launch priority or stop the active FRIB workspace merely to run a check. A command that cannot safely change an environment while it is in use may still explain that limitation; it does not turn the check into an application handoff.

Use a normal launcher when you actually want to restart the workspace or apply its queued startup update. Automated tests and demo checks use their existing disposable storage and explicit test providers.

## Unrelated applications are left alone

FRIB only stops processes verified as belonging to an older FRIB startup or its application workers. A busy port by itself is not proof of ownership. An unrelated program using a requested port is not terminated. If the selected startup cannot safely establish ownership or free the required port, it reports the conflict rather than killing another application or silently opening a second FRIB instance elsewhere.

The launchers still explain setup failures through **Show details**, the startup log and **Retry**. Retrying a normal launch follows the same latest-launch priority rule. Closing a browser tab does not stop the application services.
