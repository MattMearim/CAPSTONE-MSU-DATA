# Draft navigation and progress fix

Generating a review draft now preserves its event and review location. From an investigation, **Generate new review draft** pins **4 · Review & save** as the selected tab before the request begins. From the separate **Review & approve** page, it retains that page and event. The returned draft appears in the same review workspace.

Only the active investigation panel executes. Review & save reads its saved analysis directly when needed, without rendering the inactive evidence, analysis or guidance panels. Changing tabs does not run analysis, ask the assistant, generate a draft or submit a human decision.

The request animation stays in its original inline position. While the local service is running, the native progress display updates every **0.25 seconds**, showing a percentage labeled **estimated** and the elapsed time. The estimate is based on elapsed waiting, starts at **1%** and rises gradually to a maximum of **95%**. It is not a measurement of generated tokens or completed server work. A long request can stay at **95% estimated · Still running** until the service returns or reports an error.

A successful response sets the bar to **100%**, plays the supplied animation's completion segment and holds the checkmark in place. Draft generation does not immediately rerun the page or add a separate completion banner at another location. A failure removes the success/progress claim, shows the attention state and retains the error explanation. It does not show a checkmark or record a human approval.

Bulk transfer and import percentages remain measured: upload bytes for transfers, and server-reported processed/total files for import jobs. These are separate from the explicitly estimated progress of a blocking AI request.

Regression coverage belongs to `tests/test_draft_navigation_ui.py`, `tests/test_busy_ui.py` and the existing workflow/review suites. It checks preserved event/tab context, one generation request, inactive-panel isolation, monotonic estimated progress capped below completion, in-place updates, successful completion, and failure behavior. Final verification counts are reported with the completed build; this guide does not infer a pass count.
