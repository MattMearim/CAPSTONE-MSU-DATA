# Earlier immersive tutorial validation — November 1, 2026

This describes the earlier Apple-style version. The current Home-only green/white interface is documented in [the UI guide](UI_WORKFLOW_GUIDE.md).

83 focused UI and distribution checks passed in 49.05 seconds. The 39 review-control, dashboard and review-gate checks also passed in 15.16 seconds after the final button-icon adjustment. The suites overlap in seven review-control cases, giving 115 distinct passing checks. Existing backend data formats and AI settings were unchanged by this UI update.

Coverage includes all seven tutorial stages, current-step accessibility, safe local decorative artwork, optional first-use guidance, skip/replay, pause/resume, own-file versus demo routing, retained motion preferences, completion and shared bottom navigation. Regression cases preserve a currently selected/imported dataset instead of a stale demo and carry the current investigation into review instead of an old review selection. Complete tutorial navigation performs no imports, analysis, generation, reviews or deletions.

The radio selector was replaced by native Approve, Correct and Escalate buttons. Tests verify visible selected state, no writes on selection, correction editing and nonempty-summary validation, preserved reviewer identity, cleared acknowledgement after changing the action, and an explicit separate submission. Escalation remains excluded from approved knowledge. Tooltip-wrapped controls receive the same fill, shape and focus treatment as Submit human decision.

Browser checks on macOS covered the active system font, blue primary action, stage indicator and original inline art. The mobile layout was checked at 390 by 844 pixels: no horizontal overflow, all seven accessible stages retained and four tutorial controls at least 44 pixels tall. Temporary viewport overrides were reset. Primary text/button contrast pairs measured at least 4.7:1. No new frontend library, remote font, AI model or Python dependency is needed.

The UI change is scoped to an active tutorial; pausing or finishing restores the regular workspace theme. The decision buttons remain available in both the dedicated review page and the investigation's review step. Native keyboard operation and the app/OS reduced-motion controls remain available.
