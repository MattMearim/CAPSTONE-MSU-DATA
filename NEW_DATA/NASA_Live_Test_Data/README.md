# NASA Live Test Data for the FRIB LLM Wiki

Real public NASA data, pulled live on 2026-10-30, in the only two formats the system accepts: **CSV** and **Markdown**.

## How to load this into the FRIB app

Tested against the FRIB_OneClick project code (import, procedure search, draft citations and the Connections map), using the app's own import and document functions.

1. **Datasets** - open **1 · Add data → Bulk import**, upload `wiki_input/NASA_datasets_for_bulk_import.zip` (the 4 CSVs). In **Shared measurement mapping** you can enter `{"domain":"nasa"}` so all four group together in Connections (optional). Tick the confirmation and **Start bulk import**. All 4 import; expect *review* warnings (unitless columns, -999 values) - that is intended.
2. **Documents and procedures** - open **3 · Documents → Add procedures**, select all files in `wiki_input/documents/` and `wiki_input/procedures/` (38 files), Version `NASA-1`, tick **These files are approved for use as procedural guidance**, then **Add files**. Do not add them through Bulk import: bulk import stores documents as unapproved, and unapproved documents are never cited.
3. **Links** - open a dataset in **2 · Explore an event**, analyze it, then ask a question in **4 · Ask a question** or create a draft. The answer cites the procedures and records (S1, S2 ...), and **Connections** shows the dataset, the draft and the cited documents joined by *cites* links. Approve the draft in **5 · Review & approve** to make the links permanent.

Keep `answer_key/` and `refresh/` out of the app.

| Folder | Files | What it is |
|---|---|---|
| `wiki_input/datasets/` | 4 CSV | The data (also packed in `NASA_datasets_for_bulk_import.zip`) |
| `wiki_input/documents/` | 33 MD | `data_dictionary.md` + 32 NASA technical-report records |
| `wiki_input/procedures/` | 5 MD | Review procedures PROC-NASA-01 to 05 |
| `answer_key/` | **do not load** | 62 test questions (12 test links) with answers, plus file checksums |
| `refresh/` | **do not load** | Script that re-pulls fresh numbers from NASA in the same format |

### Links in the files
- Every CSV row has a `source_url` column: the NASA request or lookup page for that row.
- Every `NTRS-*.md` record ends with a **Links** section (its NTRS page, related records, the data dictionary). The MSU/NSCL record also links FRIB.
- `data_dictionary.md` and the procedures link the NASA documentation and the files they use.

## The datasets

| File | Rows | Source | Time column |
|---|---|---|---|
| `power_frib_hourly.csv` | 672 | NASA POWER, hourly, at MSU/FRIB (42.7245 N, 84.4746 W), Oct 1-28 2026 | `timestamp_utc` (UTC) |
| `power_frib_daily.csv` | 393 | NASA POWER, daily, same point, Oct 2025 - Oct 2026 | `timestamp_lst` (local solar time) |
| `jpl_fireballs.csv` | 89 | NASA/JPL CNEOS fireball reports since 2024 | `timestamp_utc` |
| `jpl_close_approaches.csv` | 204 | NASA/JPL asteroid close approaches within 0.02 au, Sep-Dec 2026 | `time_tdb` (TDB, not UTC; text column) |

## Things that will stress-test the system (on purpose - this is real NASA data)

- **Fill values:** `-999` means "no data" in the POWER files (5 irradiance days, plus 2026-10-28 is all -999). A system that averages them gets wrong answers.
- **Units the FRIB app doesn't know** (`au`, `mag`, `1e10 J`, `kt`, `deg`, `km`, `km/s`, `mm/h`, `mm/day`, `kWh/m^2/day`) are written into the column name (e.g. `velocity_km_per_s`), so the app imports them as unitless numbers; the units it does know stay in brackets and are converted to SI.
- **Time-standard mismatch:** the hourly file is UTC, the daily file is local solar time, so "Oct 15 rainfall" differs between them (6.86 vs 14.15 mm). Neither file is wrong.
- **Blank cells:** 31 fireballs have no velocity; one has no location.
- **Look-alike documents:** two NTRS records share the exact title "HSYE-117RH ..." but describe different tests.
- **Name variants:** Michael Campola appears under 6 spellings across 11 documents.
- **Typos as published by NASA:** "Vix-11 Pro" (meaning Virtex-II Pro).
- **A hidden control character** (U+0002) and HTML tags in `NTRS-20250006729.md`.
- **Gaps:** nothing mentions FRIB itself; the only MSU record is about NSCL (FRIB's predecessor), 2004.

## Testing
Ask the wiki the questions in `answer_key/questions.csv` (or `.md`) and compare its answers. Each question lists a category (lookup, aggregation, unit conversion, data quality, contradictions, aliases, gaps), a difficulty, and the source file(s).

## Getting fresh numbers
On a Mac with internet access: `python3 refresh/refresh_nasa_data.py`. This overwrites the 4 CSVs with current data. Afterwards the numeric answers in the answer key no longer match, but the document questions still do.

## Notes
- Sources: NASA POWER (power.larc.nasa.gov), JPL SSD/CNEOS APIs (ssd-api.jpl.nasa.gov), NASA Technical Reports Server (ntrs.nasa.gov). All public, no API key needed.
- NASA's space-weather service (DONKI) was down at retrieval time, so solar-flare data is not included.
- `answer_key/checksums_sha256.csv` lets you confirm that the files weren't changed.
