# Simple evidence workspace

The interface follows Apple's [layout guidance](https://developer.apple.com/design/human-interface-guidelines/layout): give primary tasks space, group related controls, and reveal secondary details on demand. This is a local Streamlit implementation using system fonts and native controls. No Apple assets or software are bundled.

## What changed

- A light sidebar, quiet status metrics, rounded content surfaces and a single blue action color establish a clear hierarchy.
- Datasets are actionable cards. Procedure summaries show their revision and approval state. Inventory tables and checksums remain available under labeled disclosures.
- Evidence switches among Signals, States and Notes. Only the selected view renders, and plot labels/channel selections persist when switching. Notes are searchable cards.
- Quality status remains visible; a bounded issue summary leads to source locations, repair scope and the complete downloadable report.
- The Test Lab offers dataset previews, procedure approval exercises, downloads and a presentation walkthrough. Previewing does not store a dataset. Saving an example and adding a procedure require their own buttons.
- Native charts retain units, measured coordinates, missing intervals, legends, zoom and PNG export. Raw data and full reports remain downloadable.

## Scientific and interaction boundaries

Measured evidence, derived findings, retrieved guidance and model interpretation stay separate. The named human review gate, approval exclusion for draft procedures and explicit delete/reset confirmation remain in place. Fictional examples identify their expected observations rather than asserting a physical cause or operational safety.

Uploaded labels are escaped before custom HTML rendering. Controls retain labels, focus rings and disabled states; responsive columns stack and reduced-motion preferences disable transitions. Browser verification supplements widget tests. A dedicated accessibility audit would still be needed for a conformance claim.

The earlier Grafana/Carbon workbench research remains relevant to investigation and precise evidence inspection. The current revision uses cards and progressive disclosure for everyday navigation, keeping tables as optional inspection tools.
