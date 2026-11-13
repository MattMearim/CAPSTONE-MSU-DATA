# November interface update

This update keeps the existing green-and-white theme, serif headings, human review safeguards and local AI configuration. It makes the evidence-to-review flow easier to scan and reduces the amount of source and utility information shown at once.

## Clear headings through guidance and review

Related guidance and Review & save use larger, distinct subheadings for evidence, procedure guidance, AI interpretation, draft findings and the human decision. These labels help the reviewer find the right section without treating a bold paragraph as a heading.

The review controls retain **Approve**, **Correct** and **Escalate**. Selecting an action does not save a review. A named reviewer, responsibility acknowledgement and the explicit **Submit human decision** action are still required. Switching pages or opening a source never approves a draft.

## Source bubbles that open on demand

The source panel beside an answer begins with **S1**, **S2**, **S3** bubbles rather than displaying every source's details. Select a bubble to reveal the saved passage and its available title, revision, page and section; select it again to close it. Paragraph citations can open the same source. Selection is read-only and does not ask the model again.

The retrieved passage remains distinct from measured findings and AI interpretation. **Prepare original document** and **Download original document** remain available for a valid stored source. Missing excerpts or deleted original documents still receive an explanation.

Draft source references also appear as expandable **S1**, **S2**, **S3** bubbles. Opening one reveals the complete saved reference value or metadata. A reference identifier by itself is not presented as a retrieved passage or a verified original-file link.

## FRIB logo and five numbered workspace pages

The original FRIB mark and wordmark now appear at the top left. The bundled image comes from the user-supplied saved logo-search assets and is displayed locally, with its original colors and proportions. Its source is recorded in `src/frib_ds/dashboard/assets/FRIB_LOGO_SOURCE.md`; runtime display does not fetch an image from the internet.

The sidebar shows the five core pages in order:

1. **Add data**
2. **Explore an event**
3. **Documents**
4. **Ask a question**
5. **Review & approve**

**Home**, **Knowledge library** and **Connections** remain separate entries. The bottom Next/Back workflow keeps its existing context and task order; numbering the sidebar does not submit a review or make a task complete.

## Addition items: four complete sections in one overview

Open **Addition items** and choose one section. Only that section's controls are shown, keeping the page compact while retaining the previous functions:

- **System status:** hardware and capacity details; required and optional components; installed versions, compatibility and AI configuration; explicit release checks; selected or required update plans; pending-plan review/cancellation; update results; and downloadable inventory. Browsing does not install software or queue an update.
- **Settings:** backend/service status and connection information; measurement-unit conversion with dimension and offset checks; and recorded activity, its inspection controls and downloadable JSON when activity exists.
- **Help:** the written getting-started guide, evidence-to-knowledge workflow and definitions of measured evidence, procedures, reviewed knowledge and AI suggestions. The sidebar quick-guide shortcut opens this section.
- **Try a new demo:** the existing Test Lab's fictional datasets and procedures, expected outcomes, walkthroughs, mapping presets, quality-checked previews, explicit save/import actions and downloadable example pack. Unapproved procedures stay unapproved; the approval checkbox and existing write boundaries remain in place.

Older stored destinations for System status, Settings, Help and Test Lab open the corresponding section of this overview. Help/Settings/System status can return to the previous task through **Continue your work**. Demo Next continues to an example investigation when one is selected, or Add data when no example is selected.

## Bouncing balls while working, checkmark after success

The supplied `Cred success animation.json` is bundled with a local player. Its first segment, frames **0–26**, loops while the request runs. After a successful response, the animation plays the remainder, **26–65**, then holds the final visible checkmark at frame **64**. No animation or player is downloaded during ordinary use.

Failures show an attention state and retain the normal error explanation; the checkmark is reserved for a successful response. A completed bulk job with failed files also keeps its failure/attention status. The animation does not declare an AI answer correct or approve a human decision.

The progress track distinguishes what the application can measure:

- A blocking AI/service request shows a percentage explicitly labeled **estimated**, together with elapsed time. The native progress display updates in place every **0.25 seconds** while the service runs. The waiting estimate rises gradually from **1%** and is capped at **95%**; it is based on elapsed waiting, not measured model tokens or server work. It reaches **100%** only when a successful response is ready. A slow request may remain at **95% estimated · Still running** until it returns or fails.
- Bulk uploads show measured bytes transferred to the local import queue as a percentage.
- Bulk imports show the server-reported processed-file percentage and processed/total file counts. Check the final status and per-file report: processing every file can include failures or skipped files.

The sidebar **Appearance → Gentle motion** preference and the system's Reduce Motion setting are respected. Reduced-motion users see stable status artwork and text rather than bouncing motion.

## Drafting stays on the current review step

Choosing **Generate new review draft** in an investigation pins that event and **4 · Review & save** as the active view. The separate **Review & approve** page likewise retains its selected event. Draft generation runs once, and its animation, estimated percentage and success ending update in their original inline position. Success does not force a navigation rerun or move completion feedback into a separate banner. The resulting draft appears in the same review workspace; it still requires an explicit human decision.

Only the active investigation panel executes. Opening Review & save can read its event's saved analysis without rendering or running the inactive evidence, analysis or guidance panels. Switching tabs remains a navigation action, and an inactive panel cannot trigger a hidden request or reset the visible review step. See [the draft/progress fix notes](DRAFT_PROGRESS_FIX.md).

## Home-only tutorial is unchanged

The compact interactive introduction remains available only on **Home → Start tutorial**. It pauses when opening a task page, and Home offers **Continue tutorial**, **Start over** or **Replay tutorial** as appropriate. The merged Help section does not add a tutorial launcher or bring tutorial panels into other task pages.

No real model selection, permanent model cache, saved records, ingestion limits or approval policy is changed by these presentation updates. Verification results are recorded separately for the completed build rather than inferred from this guide.
