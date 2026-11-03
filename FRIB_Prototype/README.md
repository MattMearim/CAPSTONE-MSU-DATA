# FRIB prototype — green and white workspace

This self-contained prototype is added only to `hithesh-version`, in its own folder. Existing repository files are unchanged.

## Download and run

1. Download [FRIB_Green_White_Update.zip](./FRIB_Green_White_Update.zip) using **View raw** or the download button.
2. Extract the ZIP.
3. On macOS, open `FRIB_Final_Project/START_FRIB.command`. On Windows, open `START_FRIB.cmd`.
4. Read `FIRST_STEPS.md` and `UI_GUIDE.md` in the extracted folder.

The bundle contains the complete application source, automated tests, documentation, 13 synthetic datasets and 7 procedure files (333 archive members). It includes the green-and-white UI, smaller Home-only tutorial, human review controls, Connections graph and bulk ingestion.

AI uses Ollama and sentence-transformer embeddings. The first launch may download dependencies/models; subsequent launches reuse the permanent local cache. Model weights, virtual environments, personal records, credentials and runtime databases are excluded from this repository bundle.

## Verification

ZIP SHA256: `b048ad96cfbbc52f7c99ff66b83ca815fe79275e405742be2a647a1c600f696c`

The archive contains SHA256 manifests and executable macOS launchers. The latest UI update passed 132 focused checks. Included test launchers: `RUN_UNIT_TESTS.command` and `RUN_SECURITY_CHECKS.command`.
