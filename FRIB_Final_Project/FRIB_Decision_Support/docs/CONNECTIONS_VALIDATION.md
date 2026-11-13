# Connections and interface validation — November 1, 2026

The final complete regression suite, including bulk import and performance updates, passed **1,220 tests**, with **7 optional or platform-dependent checks skipped**. Focused UI and distribution checks also passed. See [bulk import validation](BULK_IMPORT_VALIDATION.md) for the final integration evidence. The component passed JavaScript engine checks for its bounded 500-node layout, finite projection, keyboard/motion controls, safe text rendering, parent-message validation and bidirectional selection/focus state.

The running macOS workspace was checked in a real browser using its existing saved Chernobyl training example: 11 nodes and 10 explicit relationships. Checks covered selecting a dataset through the graph component, opening its details, zoom, rotation pause, app-wide motion opt-out, preserved selection, and a 390-pixel mobile layout without horizontal overflow. The full app uses the existing permanent local models and dependencies; no new models or frontend libraries were downloaded.

An offline wheel build included the graph backend and all three local component assets. Source archives exclude private runtime folders, downloaded models and user records. Relationship browsing is read-only; backend tests verified database bytes remained unchanged and rejected unsafe/missing citation pairings.

Dribbble references are credited in UI_WORKFLOW_GUIDE.md. The implementation uses original local code and existing FRIB assets.
