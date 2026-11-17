# FRIB app compatibility check - NASA live data

Run on 2026-11-17 against the code in FRIB_OneClick_Windows.zip, using the app's own API in a temporary workspace (mock AI model and the built-in hash embeddings instead of Ollama, so citations rank differently on the real app). Nothing is ingested from this file.

| Check | Result |
|---|---|
| Datasets via Bulk import (default settings + domain) | 4 imported, 0 failed |
| Documents/procedures via Add procedures (approved) | 38 indexed, 0 failed |
| Datasets analyzed and drafted | 3 of 3 returned a cited draft |
| Connections map | 8 cites links, 4 domain links, 3 draft links |

## Example citations

- **power_frib_hourly** cited: data_dictionary.md, data_dictionary.md, PROC-NASA-01_power_weather_review.md, PROC-NASA-01_power_weather_review.md, data_dictionary.md
- **jpl_close_approaches** cited: data_dictionary.md, data_dictionary.md, PROC-NASA-03_close_approach_review.md, data_dictionary.md, data_dictionary.md
- **jpl_fireballs** cited: data_dictionary.md, PROC-NASA-02_fireball_record_review.md, PROC-NASA-05_unit_conversion_reference.md, data_dictionary.md, PROC-NASA-03_close_approach_review.md
