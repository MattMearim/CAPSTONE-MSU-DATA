# Bulk import and performance validation — November 1, 2026

The complete regression suite passed **1,220 tests**, with **7 optional or platform-dependent checks skipped**, in 123.29 seconds. Tests ran against the updated source on macOS with loopback socket access for launcher checks. Disposable workspaces were used for imports, resets and adversarial cases; live user records were not changed. The 52 bulk-ingestion security checks and the updated UI/distribution checks also passed independently.

## Import and safety checks

The dashboard accepts one ZIP with a 1 GiB upload ceiling. A native folder/multiple-file picker was rejected during review because Streamlit buffers the entire selection before Python can check its aggregate size. Finder's Compress action provides folder import without that unbounded multi-file buffer. The selected archive is still held by Streamlit during upload; the dashboard's transfer to the backend uses bounded reads rather than another whole-batch buffer. The backend stages archive members on disk and imports one file at a time.

Checks covered mixed datasets and unapproved documents, preserved original bytes and relative source paths, malformed input, duplicate event IDs, per-file failures, traversal, symlinks and special files, encryption, nested archives, excessive expansion, forged ZIP sizes and CRC errors, oversized/chunked request bodies, upload counts, and aggregate entry counts across multiple ZIPs. The normal file endpoints retain their smaller request budget. Cancellation from another manager, reset during upload/processing, interrupted jobs, cleanup and report access were also exercised. Documents remain unapproved unless explicitly approved; no automatic data repair is selected.

## Performance and consistency

A synthetic benchmark with 2,400 procedure chunks measured median top-40 retrieval at 46.4 ms versus the earlier 92.0 ms. With 48 full RF events, recent-dataset listing measured 9.0 ms versus 39.7 ms. A separate 100-small-CSV bulk-import smoke test took 0.8 seconds. Fixtures, catalog size and hardware affect timings; these are not latency promises for arbitrary data or AI generation.

Retrieval ranking and tie order match the existing implementation. Only requested hits are decoded, and a large-text regression test retains under 4 MiB of peak Python allocations while searching a catalog with more than 16 MiB of source text. Index updates, deletion and reset from another worker remain visible. Existing catalogs receive additive SQLite indexes. Inactive Add data tabs do not fetch their catalogs or run their controls, and only the progress fragment polls an active import.

## Live application checks

The restarted app reported Ollama for AI and sentence-transformers for embeddings. The new bulk limits endpoint returned 1,000 entries, 1 GiB combined contents and 20 MiB per data/procedure file. In a real browser, the ZIP upload guidance, confirmation and limits were visible. The existing Chernobyl training workspace's Connections map showed 11 nodes and 10 saved relationships; selecting its dataset updated the native inspector, and graph focus synchronized with the page checkbox. The fresh browser session recorded no console warnings or errors.

Earlier Connections checks also covered camera controls, pause, app-wide reduced motion, keyboard selection and a 390-pixel viewport without horizontal overflow. The viewer is local and read-only. No new frontend dependencies or AI models are required by this update.
