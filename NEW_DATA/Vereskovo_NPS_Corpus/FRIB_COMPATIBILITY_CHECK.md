# FRIB app compatibility check - Vereskovo NPS corpus

Run on 2026-11-17 against the code in FRIB_OneClick_Windows.zip, using the app's own API in a temporary workspace (mock AI model and the built-in hash embeddings instead of Ollama, so citations rank differently on the real app). Nothing is ingested from this file.

| Check | Result |
|---|---|
| Datasets via Bulk import (default settings + domain) | 33 imported, 0 failed |
| Documents/procedures via Add procedures (approved) | 159 indexed, 0 failed |
| Datasets analyzed and drafted | 3 of 3 returned a cited draft |
| Connections map | 15 cites links, 33 domain links, 3 draft links |

## Example citations

- **DOC-1986-0028_dosimetry-night-0517** cited: PROC-VNPS-02_dosimetry_record_review.md, DOC-1986-0102_aspelund-letter.md, PROC-VNPS-01_accident_timeline_verification.md, DOC-1987-0032_revised-analysis.md, DOC-1986-0067_heli-summary.md
- **DOC-1986-0031_vega-printout-0517** cited: DOC-1987-0032_revised-analysis.md, DOC-1986-0098_intl-briefing.md, PROC-VNPS-06_root_cause_document_review.md, DOC-1988-0003_archive-finding-aid.md, DOC-1987-0021_trial-day9.md
- **DOC-1987-0011_registry-1987** cited: DOC-1988-0003_archive-finding-aid.md, DOC-1987-0030_health-registry.md, DOC-1987-0007_u3-slip.md, DOC-1987-0027_resettlement-1987.md, DOC-1986-0026_unit3-handover.md
