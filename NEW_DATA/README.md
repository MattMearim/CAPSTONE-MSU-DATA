# NEW_DATA - FRIB-compatible test data with links (2026-11-17)

| Folder | What it is |
|---|---|
| `NASA_Live_Test_Data/` | Real NASA data (POWER weather at FRIB, JPL fireballs and asteroid close approaches, 32 NTRS radiation-test report records) + 5 review procedures. Every row/record links to its NASA source. |
| `Vereskovo_NPS_Corpus/` | Fictional Chernobyl-style nuclear plant corpus: 153 Markdown records + 33 CSV tables (1985-1987) + 6 review procedures, with cross-document links and an archive index. |

Both were checked against the FRIB app code: all datasets import with Bulk import, all documents index with **Add procedures** (approved), drafts cite them, and the Connections map shows the links. See each folder's `README.md` for loading steps and `FRIB_COMPATIBILITY_CHECK.md` for the results.

Do not import the `answer_key/` folders or `world_bible.md` into the app - they are for grading.
