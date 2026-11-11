# FRIB single-instance startup update

Download [FRIB_Single_Instance_Fix.zip](./FRIB_Single_Instance_Fix.zip) using **View raw** or the download button, then extract it. This is the complete project, including the earlier interface and live draft-progress fixes.

On macOS, open `FRIB_Final_Project/START_FRIB.command`. On Windows, use `FRIB_Final_Project/START_FRIB.cmd`. Read the included `FIRST_STEPS.md` and `UI_GUIDE.md`.

Normal startup now gives the most recently opened FRIB project priority. The launcher safely shuts down verified older FRIB instances before starting the new workspace. Saved records and permanently cached AI models are retained. Unrelated applications are not stopped. Each selected project retains its own data directory.

The latest startup fix passed 166 focused checks. On the development Mac, both legacy and registered-instance handoffs were verified with the old processes stopped, one replacement workspace healthy, and the existing Ollama and semantic embedding models reused.

The archive contains 351 members: complete source, tests, documentation, launchers, synthetic datasets and procedure files. Model weights, virtual environments, credentials and runtime records are excluded.

SHA256: `c3777910e972e06e28f9ba66ab55a510aa0baf2b182a7995e3630b968c6302f4`

This addition is isolated to `FRIB_Prototype` on `hithesh-version`. Earlier bundles remain available.
