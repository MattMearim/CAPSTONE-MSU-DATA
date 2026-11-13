# Import a folder or ZIP

Open **Add data → Bulk import**. In Finder, right-click your folder and choose **Compress**, then upload the resulting ZIP. The app accepts one size-capped archive so a large folder is not buffered as thousands of files in Streamlit memory before its total size can be checked. ZIP members are staged and processed on disk. The folder hierarchy is recorded as source metadata; files with the same name in different folders remain separate originals.

Select your collection, review the selected-file list, check the import confirmation, and choose **Start bulk import**. Upload progress shows transfer to the local queue. A background worker then processes one file at a time and reports imported, failed and skipped files. You can use other pages while it works and return to this tab. Keep FRIB running until the batch finishes.

- CSV and TSV files become measurement datasets using detected columns and recorded units. Use **Shared measurement mapping** for consistently formatted collections; for example `{"domain":"rf","time_column":"time_s","time_unit":"s"}`. Existing mapping keys such as `column_roles`, `signal_names`, `source_units`, `target_units` and `unit_columns` are supported. Files needing corrections are reported individually. No repair is silently selected.
- JSON files must contain an exported FRIB EngineeringEvent. Supplied IDs and provenance are retained; an existing event ID cannot be overwritten.
- LOG files preserve narrative evidence. PDF, TXT and Markdown files enter the document library **without approval**. Review and explicitly approve references in Documents before using them for AI answers.
- ZIP files are checked before importing. Hidden Mac metadata and unsupported files are listed as skipped. Nested/encrypted archives, unsafe paths, links and excessive expansion are rejected.

A batch supports **up to 1,000 files** and **1 GiB of combined expanded contents**. Each measurement or procedure file may be **up to 20 MiB**; split larger captures into smaller files while retaining their timestamps and units. ZIP entry limits include folders and metadata entries. Tabular imports also retain the existing limits of 250,000 rows, 64 columns and 1,000,000 cells. Server settings can lower these ceilings.

Choose **Stop after current file** to cancel safely between files. Completed imports remain saved. Download the per-file JSON report and retry only the files that need attention. A stopped application does not automatically resume a partly completed import; its report explains that interruption. Resetting the workspace cancels imports and removes their uploaded staging files and report details.

## What runs faster

The dashboard streams multipart uploads instead of assembling a second whole-batch byte buffer. Temporary staging is cleared when work finishes, and uploaded browser buffers are released after the backend accepts the batch. A bounded worker keeps simultaneous jobs from competing for memory. Only the active Add data tab runs; progress polling refreshes its small status section, rather than rerendering the whole app.

Procedure search now ranks vectors before decoding source passages and streams the catalog into a small top-hit heap. It does not load all source text into memory or maintain a stale cache. New SQLite indexes accelerate recent-dataset and related-record lookups. Saved data, cosine ranking, real AI models and deletion/reset behavior are preserved.

A disposable synthetic benchmark with 2,400 procedure chunks and 48 full RF events measured median retrieval at **46.4 ms**, compared with **92.0 ms** before optimization, and recent-dataset listing at **9.0 ms**, compared with **39.7 ms**. A separate local smoke test imported 100 small CSV datasets in **0.8 seconds**. These measurements describe those fixtures; larger files and hardware differ. No live user records or AI generation were used for the benchmark.
