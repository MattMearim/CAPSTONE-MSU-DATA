# Startup, sources and guided navigation

The current compact AI settings, chart controls, hideable telemetry and complete evidence-to-knowledge workflow are described in [Workspace workflow](PRODUCT_WORKFLOW.md). Explore opens on the chart; View holds display controls, and AI quality review, Data checks and Files & exports sit below it.

For the current heading, navigation and run-animation changes, see [the November interface update](UI_NOVEMBER_UPDATE.md).

## Open and close the workspace

Double-click **START_FRIB.command** on macOS. Its startup window shows the actual preparation stages: **Preparing application**, **Preparing AI**, **Starting workspace** and **Ready**. The browser opens when the workspace is ready. Downloads may take time on the first launch; later starts reuse cached files.

- **Show details** reveals the technical log when you need it.
- **Retry** becomes available after a failed attempt finishes cleaning up.
- **Open workspace** brings the browser back.
- **Stop workspace** stops the services started by that window. Closing the window asks whether to stop.

A newer normal launch now has priority across project copies: it safely stops the older FRIB workers, starts the selected project with its own saved records, and gives the newest startup window control of the new workspace. Models and saved files remain on disk. Queued updates for the selected project apply after the handoff. Checks/setup/test commands do not take over a running app; `--no-browser` normal launches follow the same one-active-workspace policy, and `FRIB_NO_GUI=1` explicitly uses the console. See [single-instance startup](SINGLE_INSTANCE_STARTUP.md).

## A smaller introduction, only on Home

Choose **Home → Start tutorial** for a compact seven-stage overview. **Continue** and **Back** browse the introductions on Home. **How to try this step** opens the detailed instructions. **Open Add data**, **Open Documents** or the corresponding workspace button takes you to that page and pauses the guide. Return Home and choose **Continue tutorial** to pick up where you left off. **Pause**, **Start over**, **Skip for now** and **Replay tutorial** remain available as appropriate. Sidebar and Help pages do not launch the tutorial, and no tutorial panel follows you into task pages. The normal bottom Next/Back controls continue through the workspace independently.

The interface keeps the familiar serif headings and soft visual character. Forest-green actions, white surfaces and pale mint/sage accents tie the cards, navigation, uploads and Connections viewer together. Secondary chart/category colors remain distinct, and warnings/errors keep their meaning. The tutorial uses a small local icon and optional instructions instead of a large illustration or a separate app-wide theme.

Under **Human decision**, use the **Approve**, **Correct** and **Escalate** buttons. The selected action has a check and a filled green appearance matching the submit control. Correct opens editable fields. Changing your action clears the responsibility acknowledgement so you can confirm the new decision; your reviewer name stays in place. Only **Submit human decision** records a review. Tutorial navigation and action selection do not save or approve anything.

All artwork and styles run locally. **Appearance → Gentle motion**, the system's Reduce Motion setting, visible keyboard focus and narrow-screen controls remain supported.

## Check the sources beside an answer

In **Related guidance** or **Ask a question**, the answer and source viewer appear side by side. The right-hand source panel starts with compact **S1**, **S2**, **S3** bubbles. Choose a bubble in the panel or beside a cited paragraph to open its passage; choose it again to close it. The selected passage is highlighted with its document title, revision, page and section when recorded. Unopened source details stay out of the way. Draft source references also use expandable **S1**, **S2**, **S3** bubbles, preserving the recorded reference without inventing a passage.

The highlighted passage is the retrieved excerpt saved with the answer. It may be shortened; it is not a replacement for the full procedure. Choose **Prepare original document**, then **Download original document** when you need the original file. If the original has been removed, the saved excerpt remains visible with an explanation.

Measured or calculated findings, retrieved procedures and AI interpretation keep separate labels. Switching passages does not ask the model again. Missing citations or unavailable excerpts are called out rather than presented as verified support.

## Follow the next step

Use **Next** and **Back** at the bottom of each page. The main path is **Home → Add data → Documents → Explore an event**. Within the investigation, Next advances through **Your data → What changed → Related guidance → Review & save**, then opens the knowledge library. The same selected dataset stays with you.

The separate **Review & approve** page also keeps the selected dataset. **Addition items → Help**, **Settings** and **System status** offer **Continue your work**, returning to the same investigation tab. A newly selected dataset starts at its own evidence view. The Home tutorial has its own compact controls; bottom Next/Back controls follow the regular workspace route.

Next and Back only navigate. Importing, running analysis, generating a draft and submitting a human decision remain explicit actions on their respective screens. Moving to the knowledge library does not approve a draft.

**Generate new review draft** preserves the selected event and current review view. From an investigation it keeps **4 · Review & save** selected; from **Review & approve** it stays on that page. Progress and the completion/checkmark ending remain inline at the request location, followed by the draft. Only the active investigation panel executes, so opening Review & save does not run hidden evidence, analysis or guidance panels. The review panel can read its saved analysis directly. See [the draft/progress fix notes](DRAFT_PROGRESS_FIX.md).

## Find utility pages without crowding the sidebar

The sidebar numbers the core pages **1 · Add data**, **2 · Explore an event**, **3 · Documents**, **4 · Ask a question** and **5 · Review & approve**. Home, Knowledge library and Connections keep their own entries. The official FRIB logo appears at the top left from a bundled local image.

Open **Addition items** for four sections: **System status**, **Settings**, **Help** and **Try a new demo**. Only the selected section is displayed. System status retains hardware inventory, required and optional software, AI configuration, release checks, explicit update plans and inventory download. Settings retains service connection information, measurement-unit conversion and recorded activity with downloads. Help retains the written guide, workflow explanation and evidence-label definitions. Try a new demo retains fictional datasets, procedures, preview/import presets, expected outcomes, walkthroughs and bundle downloads. Selecting a section does not import files or queue updates.

## Follow a running request

The supplied bouncing-ball animation loops through frames **0–26** while a request is running. After a successful response, it plays the remaining sequence through frame **64** and holds the checkmark. Failed requests show an attention state and the existing error explanation; they do not show a success check.

The distinct progress track labels what is being measured or estimated. Blocking AI requests show an explicitly **estimated** percentage and elapsed time, updating in place every **0.25 seconds**. This waiting estimate starts at **1%**, rises gradually and stops at **95%** until the response is ready; it does not measure model tokens or server work. Only a successful response reaches **100%**. Bulk transfers show measured upload percentages; bulk import shows completed-file percentages and the processed/total file counts. A bulk job can finish with failures, so check its status and per-file report rather than treating a full bar as proof that every file succeeded. Gentle motion and system Reduce Motion preferences remain supported.

## Import a collection

Choose **Add data → Bulk import** to upload a ZIP of a folder or file collection. A background job shows per-file progress and a downloadable result report; **Stop after current file** preserves completed imports. Procedures remain unapproved. See [the bulk import guide](BULK_IMPORT_GUIDE.md) for formats and practical limits.

## Explore the Connections web

Open **Connections** in the sidebar for an interactive 3D map of your saved workspace. Drag to orbit, scroll or use **+ / −** to zoom, and choose a point to inspect its details. **Jump to an item** provides the same selection with the keyboard. **Focus on the selected idea** highlights its immediate neighbors; **Open dataset**, **Open procedure**, or the corresponding record button returns to the original workspace.

The map uses saved datasets, analysis findings, document citations, review records, domains and tags. Relationships have explicit labels in **Connection list**. Shared tags and domains are categories, not proven causes. AI drafts remain distinct from reviewed knowledge. Missing or deleted sources do not become invented links. Large workspaces show a bounded view; original records remain available in their libraries. Empty projects show starting actions rather than a sample map.

The 3D viewer runs locally without external JavaScript libraries, model downloads or AI requests. Choosing a point, searching, changing focus or moving the camera does not change records or approvals.

## Choose the amount of motion

The workspace uses brief page entrances and responsive hover, focus and press feedback. Choose **Appearance → Gentle motion** in the sidebar to turn decorative motion off. The graph also provides **Pause rotation**. System Reduce Motion preferences are respected. Camera controls remain available when automatic motion is off.

Visual references: [SlabPixel's Norde dashboard](https://dribbble.com/shots/27281376-Norde-Sustainability-driven-AI-Dashboard) and [Philip Litassy's Knowledge Graph](https://dribbble.com/shots/10993702-Knowledge-Graph) informed the restrained cards, spacing and graph presentation. FRIB uses its own code and local assets.

## Earlier verification

The updated complete regression suite passed **1,069 tests**, with **7 platform-dependent checks skipped**. Focused UI checks covered source selection, safe excerpt display, dataset preservation, tutorial navigation, and returning to the same investigation tab. A real native window reopened the existing app, showed Ready and left its original services running after the new window closed. Native widget layout and startup failure controls were also checked on macOS.
