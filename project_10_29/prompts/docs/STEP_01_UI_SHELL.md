# Historical note: Step 1 application shell

This file records the earlier navigation/usability milestone. The project has since grown into a functional four-level prototype with persistent evidence, analysis, approved-document retrieval, review gates, file management and exports. Use [README.md](../README.md), [START_HERE.md](../START_HERE.md) and [the requirements matrix](REQUIREMENTS_MATRIX.md) for current behavior and limitations.

## Current navigation

The dashboard now has nine pages:

1. **Home** — quick actions and workflow overview.
2. **Create Dataset** — synthetic generation, CSV/JSON import, preview, export and confirmed dataset deletion.
3. **Investigate Event** — raw evidence, original attachments, Level-2 analysis, event-specific procedural context and human review.
4. **Files & Documents** — reference uploads, approval controls, search, originals and confirmed document deletion.
5. **Ask Assistant** — search approved procedure content with traceable excerpts.
6. **Review Results** — reopen saved drafts, correct ordinary fields and explicitly Approve, Correct or Escalate.
7. **Engineering Wiki** — search and download human-reviewed knowledge.
8. **Settings** — connection/provider status and recorded activity; configuration editing remains outside this page.
9. **Help** — workflow guidance and evidence labels.

The workflow remains **Create -> Analyze -> Ask -> Review -> Save**. Raw evidence, derived measurements, retrieved guidance, interpretation and reviewed knowledge are labeled separately. The application has no machine-control connections.

## Run the current project

Double-click **Start FRIB.cmd** in the project folder. On a fresh computer, install Python 3.11 or newer with PATH enabled and allow internet access for first-time dependencies. The starter creates a private environment, starts both services, checks readiness and opens the dashboard. Keep the launcher window open; press Ctrl+C there to stop both services.

From a terminal, `python start.py` does the same thing. Use `python start.py --check` for an installation check. There is no need to start two separate terminals for routine use.

## Validate the current workflow

Generate an example, investigate its evidence, run analysis, add an approved demonstration reference, inspect retrieved excerpts, submit a named human review, and find approved/corrected results in Engineering Wiki. Restart to verify persistence. Use only disposable examples to exercise confirmed deletion.

The automated suite now covers the functional prototype, including UI navigation and review/file controls. See [the validation plan](VALIDATION_PLAN.md) for current checks and remaining sponsor validation; the original shell milestone's test count is not the current project's validation status.
