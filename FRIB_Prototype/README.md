# Current FRIB project — Mac-ready update

**[Download FRIBCURRENTPROJECT.zip](FRIBCURRENTPROJECT.zip)** using the download button or **View raw**, then extract the entire ZIP.

## Start on macOS

1. Open the extracted `Ayman_Current_Project` folder.
2. Double-click **START_AYMAN.command**.
3. Keep the startup window open while using the app. It prepares missing dependencies, starts the local services, and opens the workspace.

The launcher finds the source relative to itself. Keep the extracted folder together. A supported 64-bit Python 3.11–3.13 installation is required. First setup may download missing packages or models; later launches reuse the private runtime and permanent per-user AI cache.

## What is included

This complete source package updates Ayman's `aymanfull-zip` project for macOS and publishes the checked copy on `hithesh-version`. It includes configurable real AI and semantic embeddings, model management, the Data Quality Agent, evidence import and analysis, cited guidance, human review, the knowledge library, interactive UI, synthetic test inputs, and procedures.

The Mac update removes forced model overrides and canned real-AI draft substitutions, fixes first-install dependency validation and upgrade registration for psutil, and fixes duplicate citation controls in the knowledge view. It also supplies a portable one-click Mac launcher and configurable AI context/output budgets.

**Verification on November 13, 2026:** 1,463 tests passed, 7 skipped. Real Qwen inference and SentenceTransformers retrieval produced a cited answer and a `configured_llm` draft using disposable fictional RF data. The existing AI model cache was reused.

Read `READ_ME_FIRST.md` and `LOCAL_CHECK_REPORT.md` inside the extracted folder for setup and verification details. The full application source is in `CAPSTONE-MSU-DATA-aymanfull-zip/FRIB_Final_Project/FRIB_Decision_Support`.

## Archive verification

- 414 archive members; 3,476,887 bytes.
- SHA256: `ac1118bde9d159d2b6ce71f6020b91dd0894bca24a9f0233b4e96413093b2c7a`.
- ZIP integrity, all three internal checksum manifests, and executable Mac launcher permissions were verified.
- Installed environments, model weights, credentials, and saved runtime data are excluded.

One current project ZIP is kept in this folder. Previous downloads remain available through Git history.
