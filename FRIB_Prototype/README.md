# Current FRIB project

**Download [FRIBCURRENTPROJECT.zip](FRIBCURRENTPROJECT.zip)** using the download button or **View raw**, then extract it.

1. On macOS, double-click `FRIB_Final_Project/START_FRIB.command`.
2. On Windows, double-click `FRIB_Final_Project/START_FRIB.cmd`.
3. Follow `FIRST_STEPS.md` or the Home-page tutorial in the extracted project.

This is the complete current project, including the latest interface, live draft progress, and single-instance startup fixes. The newest launch takes priority over older verified FRIB instances. It includes source code, automated tests, documentation, 13 synthetic datasets and 7 procedure files.

The first launch may download required dependencies and AI models; later launches reuse the permanent local cache. Model weights, virtual environments, personal records, credentials and runtime databases are excluded from this download.

Only one current ZIP is kept in this folder. Older versions are available through Git history. This consolidation affects `hithesh-version` only.

**Archive verification:** 351 members; SHA256 `c3777910e972e06e28f9ba66ab55a510aa0baf2b182a7995e3630b968c6302f4`.

For checks, use the included `RUN_UNIT_TESTS.command` and `RUN_SECURITY_CHECKS.command` launchers.
