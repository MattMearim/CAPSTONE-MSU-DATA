# Fictional Test Lab execution

Status: **passed**. 32/32 grouped checks passed.

Real local API lifecycle; mock LLM/hash embeddings/SQLite; temporary app storage removed at exit.
Saved project data was not touched. Run timestamps and generated record IDs vary; input fixtures and expected engineering values are deterministic.

- **PASSED LAB-EMPTY** - Fresh isolated store and insufficient-context response
  No saved records and no false grounding.
- **PASSED DOC-RF-A** - RF cavity trip evidence review / LAB-A
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-RF-B** - RF cavity trip evidence review / LAB-B
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-RF-DRAFT** - RF cavity trip evidence review / LAB-C-DRAFT
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-RF-XRAY** - RF X-ray gradient scan review / LAB-1
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-PLC** - PLC controls state sequence review / LAB-1
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-MECHANICAL** - Mechanical vibration bearing review / LAB-1
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DOC-CRYO** - Cryogenic helium temperature pressure review / LAB-1
  Exact original, explicit approval, version and approved-only indexing.
- **PASSED DATA-RF-TRIP** - RF trip with recorded interlock
  Valid RF analysis: recorded reference at 0 s, 100 Pa pressure increase and approximately 25 ms field threshold crossing. Coincidence is not causation.
- **PASSED DATA-RF-XRAY** - X-ray and gradient scan
  Gradient becomes V/m; X-ray remains counts/s. Scatter/trend plots describe co-variation without proving field emission or safe gradient.
- **PASSED DATA-CRYO** - Cryogenic temperature with capture gap
  Celsius becomes kelvin and mbar becomes Pa; the capture gap and declared stability/bound differences are flagged. Generic evidence summary, no cryogenic diagnosis.
- **PASSED DATA-PLC** - PLC states, permit and log messages
  RUNNING -> WARNING -> INTERLOCKED is observed; transition times are 4 s and 7 s. Boolean permit remains categorical and all 21 text records survive.
- **PASSED DATA-UNITS** - TSV with mixed scales and offset units
  Voltage [1,2000,0.5] V, temperature [273.15,293.15,373.15] K, pressure [1000,2000,1000] Pa, fraction [0.25,0.5,1]. Original TSV bytes remain unchanged.
- **PASSED DATA-REPAIR** - Damaged capture requiring explicit repairs
  Raw import is blocked with no writes. Only the listed explicit repairs produce a valid copy. Original bytes and repair receipt remain downloadable; no missing measurements are filled.
- **PASSED DATA-QUALITY** - Gap, jump and flatline expectations
  Missing cadence/channel, voltage bound/stability and repeated-sample checks appear. They flag data/declared expectations and do not prove sensor failure or negligence.
- **PASSED DATA-BAD-UNIT** - Incompatible physical dimensions
  Validation blocks the incompatible V/Pa dimension; preview and failed save persist no event.
- **PASSED DATA-DBM** - Unsupported logarithmic unit
  Unsupported dBm is blocked. Convert outside this app with a reviewed reference and import a supported unit; do not relabel numeric readings as W.
- **PASSED DATA-MECHANICAL** - Mechanical vibration native JSON
  Mechanical analysis observes approximately 12 Hz post-event oscillation and higher RMS. Temperature normalizes to K; alignment is derived and original grids remain unchanged.
- **PASSED DATA-UNTIMED** - Capture without measured timestamps
  Unitless row order is explicit; generic evidence analysis is used for this incomplete RF capture, with no invented physical timing.
- **PASSED DATA-LOG** - Timestamped operator log
  Four source lines retained; PLC_STATE transitions support sequence analysis, but no unrecorded waveforms or physical cause are invented.
- **PASSED DATA-PDF-NOTE** - Selectable-text PDF evidence
  Selectable text is retained as logs with page provenance; mixed untimed headings mean explicit row-order coordinates. No OCR, image/table interpretation or numeric diagnosis.
- **PASSED RAG-APPROVAL** - Approved-only retrieval, visible revision metadata and measured evidence
  Approved A and B may coexist; unapproved C is excluded, with no generated AI interpretation.
- **PASSED RAG-FORMATS** - PDF, text and Markdown retrieval across engineering domains
  Each relevant approved domain procedure can be retrieved; PDF source has page metadata.
- **PASSED REVIEW-RF-TRIP** - Human approve / RF trip with recorded interlock
  Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.
- **PASSED REVIEW-RF-XRAY** - Human escalate / X-ray and gradient scan
  Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.
- **PASSED REVIEW-PLC** - Human correct / PLC states, permit and log messages
  Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.
- **PASSED REVIEW-MECHANICAL** - Human approve / Mechanical vibration native JSON
  Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.
- **PASSED REVIEW-LOG** - Human escalate / Timestamped operator log
  Named review required; approve/correct publishes knowledge, escalation does not; duplicate review rejected.
- **PASSED RAG-RETIRE** - Explicit revision retirement removes retrieval and original
  No automatic supersession is claimed; explicit deletion retires A and preserves B.
- **PASSED FILES** - Add, download and remove a supporting file
  Selected file is removed; original evidence and event remain.
- **PASSED RESTART** - Stored evidence, analyses, reviewed knowledge and retired revisions survive restart
  Persistent SQLite/vector state reproduces current records without resurrecting deleted revisions.
- **PASSED DELETE** - Event deletion removes original files and dependent derived records
  Deleting one test event cascades its files, analysis, draft, review and knowledge.

Limits:
- No live FRIB integration, operational approval or causal-accuracy validation.
- Mock retrieval is extractive; local AI providers are not tested.
- No OCR or PDF image/table interpretation.
- Approved revisions coexist until explicitly retired; no automatic supersession.
