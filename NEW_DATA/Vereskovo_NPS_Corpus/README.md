# Vereskovo NPS test corpus (fictional, modeled on the 1986 Chernobyl accident)

A synthetic multi-document corpus for testing an LLM wiki. Built from `chernobyl_corpus_prompt.txt`.
Everything is fictional: the station, town, people, agencies and documents. The general sequence of events and the reactor physics follow a Chernobyl-type accident.

## How to load this into the FRIB app

Tested against the FRIB_OneClick project code (import, procedure search, draft citations and the Connections map), using the app's own import and document functions.

1. **Datasets** - open **1 · Add data → Bulk import**, upload `Vereskovo_datasets_for_bulk_import.zip` (all 33 CSVs). In **Shared measurement mapping** you can enter `{"domain":"vereskovo"}` so they group together in Connections (optional). Tick the confirmation and **Start bulk import**. All 33 import; *review* warnings (unitless columns, blank cells, row-order tables) are expected.
2. **Records** - open **3 · Documents → Add procedures**. For each folder `corpus_by_batch/batch_01` ... `batch_08`, select all the Markdown files (the file picker only shows .md/.txt/.pdf), Version `VNPS-1987`, tick **These files are approved for use as procedural guidance**, **Add files**. Load the batches in order - that is the incremental test. Don't use Bulk import for these: it stores documents as unapproved, and unapproved documents are never cited.
3. **Procedures** - same screen, select the 6 files in `procedures/`, Version `VNPS-1`, approved, **Add files**.
4. **Links** - open a dataset in **2 · Explore an event**, analyze it, then ask a question in **4 · Ask a question** or create a draft. Answers cite the records and procedures (S1, S2 ...), and **Connections** shows the dataset, the draft and the cited documents joined by *cites* links. Approve the draft in **5 · Review & approve** to keep it.

The 33 CSVs are also in `corpus/` and in the batch folders (so the batches stay complete), but import them only once, from the zip.

| Folder / file | What it is |
|---|---|
| `Vereskovo_datasets_for_bulk_import.zip` | The 33 CSV data tables |
| `corpus_by_batch/batch_01-08` | All 186 records in date order (153 Markdown records are what you upload as documents) |
| `corpus/` | Same records in one folder |
| `procedures/` | 6 review procedures |
| `manifest.csv` | Every record with date, type, author, links and batch |

## Links (new)

- Every Markdown record ends with an **Archive references** section: clickable links to the records it cites, later records that refer to it, neighbouring records in the same file series, and its data extracts.
- Every CSV has a `related_document` column naming the record it belongs to.
- `DOC-1988-0003_archive-finding-aid.md` (in batch_08) is an index that links to every record.
- `manifest.csv` has `link` and `links_to` columns.
- Links are relative file links (`DOC-1986-0018_dosimetry-report-0517.md`); inside `corpus_by_batch` they point across batch folders (`../batch_03/...`). The records are fictional, so they have no web addresses.

## Procedures (new) - upload as procedures

`procedures/` holds 6 fictional review procedures (PROC-VNPS-01 to 06) in the same style as the FRIB demo procedures. Each links to the records it uses; PROC-VNPS-02 and -05 also link real outside references (U.S. NRC, CDC, NIST) for radiation units.

## Do NOT feed the wiki (grading only)

| File | What it is |
|---|---|
| `answer_key/evaluation_questions.csv` / `.md` | 146 questions (12 of them test links) with answers and supporting doc IDs |
| `answer_key/link_ledger.md` | Every link in the corpus, CSVs and procedures |
| `answer_key/contradiction_ledger.md` | 33 seeded contradictions (4 genuinely unresolvable) with resolutions |
| `answer_key/supersession_ledger.md` | 25 facts that change over time (old -> new) |
| `answer_key/gaps_ledger.md` | 14 facts that are referenced but never documented |
| `answer_key/seeded_issues.md` | Typos, duplicates, header errors, rumours, numbers that don't add up |
| `answer_key/alias_ledger.md` | Every alias / spelling variant |
| `answer_key/entity_registry.md` | 71 people, 50 equipment items, 22 settlements, 24 organizations, materials, projects |
| `answer_key/timeline.md` | Master timeline |
| `world_bible.md` | The whole world definition and the planned document list |

## Main storylines

1. The turbine rundown safety test and its program revisions
2. The accident night - conflicting times and accounts
3. Radiation underestimated (meters at the top of their scale)
4. Firefighters and medical consequences
5. Evacuation - "temporary, three days" becomes permanent
6. Foreign detection before the official announcement
7. Root cause shifts from operator error (1986) to design flaws (1987)
8. Helicopter drops, the bubbler pool, the tunnel
9. Shelter construction, robots that fail
10. Liquidator dose records and the registry change
11. Trial
12. Units 1-3 restart dates slipping
13. Leadership changes
14. A chronic pump vibration problem

## How the CSVs are laid out for the FRIB app

- **Units the app knows** stay in brackets and are converted to SI on import: `[MW]`, `[C]`, `[%]`, `[m]`, `[s]`, `[mm/s]`, `[um]`.
- **Units the app doesn't know** are in the column name, so the app imports them as unitless numbers: `dose_rate_R_per_h`, `dose_rate_mR_per_h`, `cs137_soil_Ci_per_km2`, `drum_pressure_kgf_per_cm2`, `orm_rod_equivalents`, `release_rate_MCi_per_day`, `total_dose_rem`, `cost_thousand_rubles` ...
- **Time series** have a `timestamp...` column (`timestamp_local`, `timestamp_plant_computer`, `timestamp_utc` for the Varnland data). Times without a zone are stored by the app as UTC - the records are in local (Moscow) time.
- **Tables that are lists, not time series** (settlements, patients, registry, drops, costs ...) keep their date as a text column (`sample_date`, `drop_date`, `report_month` ...), so the app uses row order. This is also why the duplicated 23 May helicopter row is still there.
- Multi-location readings are one column per location or pump (e.g. `U4-MCP-03 vibration [mm/s]`), because the app needs one value per column per timestamp.
- Still in the data on purpose: blank cells, a column with no unit (`gross_beta`), `>200` pocket-dosimeter readings (kept as text in `reading_as_recorded`; the number column is blank), scientific notation (`6.1e-07`), the duplicated helicopter row, the mistyped pump ID (noted as `U4-MPC-03` in the vibration log) and the misspelled `Kozhukivka`.
