# Final live-demo bundle validation — October 12, 2026

The final distribution contains the complete application and a separate `Live_Demo_Data` folder with **13 datasets and 7 fictional procedures**. Input bytes are preserved, each input's SHA-256 and size are checked against its manifest, and all archive contents receive checksums.

The portable demo manifest is at `Live_Demo_Data/configuration/test_lab/manifest.json`. Its paths resolve within `Live_Demo_Data`, so the actual runner exercises the separate `datasets` and `procedures` files rather than silently using the application's internal sample copies.

Verification completed:

- The complete project suite was rerun after the final startup correction: **670 passed, 1 skipped, 0 failures** in 206.37 seconds. The skipped test requires directory symlink permissions unavailable to this Windows account. Two external deprecation warnings remain.
- **32/32 grouped API checks passed** against the extracted archive's separate demo inputs. This includes original-file preservation, units, corrupted captures and explicit repairs, recording gaps and declared signal expectations, RF/mechanical/PLC processing, narrative logs and selectable-text PDFs, approved-only retrieval and revision retirement, human approve/correct/escalate decisions, persistence, attachments and dependent deletion.
- **7 targeted Test Lab and source-distribution tests passed**, including loading the extracted source independently of the original project.
- All **20 source hashes** match, all portable manifest paths stay inside the demo folder, RF draft C remains unapproved, and no repair is preselected in default import options.
- The actual **START_LIVE_DEMO.cmd** from the extracted bundle installed its missing environment and started both API and dashboard successfully using an existing system Python 3.13.0. A generated RF event and analysis were saved in `Demo_Workspace`; the normal running application's record counts remained unchanged. Alternate local ports were used for this verification so the normal app could remain running.

This additional first-run test exposed an old bundled pip failure when venv ran ensurepip from an extended Windows working path. Setup now creates the environment without pip, then runs ensurepip explicitly from the ordinary project folder, logging its complete diagnostics. A fresh environment at the same deep path and the complete demo launcher both passed after this correction. **42 focused startup tests passed**, including the new regression.

`START_LIVE_DEMO.cmd` explicitly uses the application's source configuration and stores presentation records in the sibling `Demo_Workspace`. It forces mock/hash/SQLite providers, requires no AI service key or model download, and leaves normal application data separate. Both launchers use the same default local ports; stop the running launcher with Ctrl+C before switching.

`RUN_DEMO_CHECKS.cmd` runs the supplied separate manifest through the application using disposable storage and writes its results to `Demo_Check_Results`. It does not reset a saved workspace. First-time setup can require internet access.

The guide at `Live_Demo_Data/README.md` provides a timed 15-minute presentation, exact filenames, import mapping references, expected measurements and additional scenarios. Sidecar JSON settings are reference material; ordinary file upload does not automatically read them. Test Lab offers the matching presets.

All demo inputs are fictional. The checks exercise local application behavior in mock/hash/SQLite mode; they do not certify real FRIB operating procedures, infer proven causes, operate equipment or test optional AI model quality. See `STARTUP_VALIDATION_REPORT.md` for the prior complete system checks and platform limitations.
