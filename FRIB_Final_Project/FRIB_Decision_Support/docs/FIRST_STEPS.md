# Your first few minutes in FRIB

FRIB helps you bring files together, explore what happened, find guidance and keep findings that a person has checked. You can browse the seven-stop tutorial in about **five minutes**. Allow extra time if you want to try each task.

## Open the app

On macOS, double-click **START_FRIB.command** in the main project folder. For practice with a separate demo workspace, use **START_LIVE_DEMO.command** instead. If you have only the source folder, use **Start FRIB.command** there. On Windows, use the corresponding **.cmd** launcher. Extract the complete project before launching it.

On macOS, just open **START_FRIB.command** (or **Start FRIB.command** inside the source folder). It automatically prepares missing dependencies and models, starts the services and opens the dashboard. First setup needs internet for missing downloads; later launches and fresh project copies reuse the permanent AI files in **~/Library/Application Support/FRIB**. The separate **SETUP_LOCAL_AI.command** is optional for setup or repair. Normal use runs Ollama **qwen3:8b** with **all-MiniLM-L6-v2** semantic embeddings. Both normal and demo launchers use these real models. The macOS launcher needs a compatible 64-bit Python 3.11, 3.12 or 3.13 and explains what to install if it cannot find one. The startup window shows preparation progress and opens the dashboard when ready. Keep the newest startup window open while you work and choose **Stop workspace** when finished. To restart or change project copies or modes, open the desired normal launcher: the latest launch safely stops older FRIB workers and opens that project's own saved workspace. A queued update for the selected project applies after this handoff. Terminal-only launches still support **Ctrl+C** for a manual stop.

## Follow the guided tutorial

1. **Welcome — find your way around.** On Home, choose **Start tutorial** from the welcome invitation, or **Skip for now** to explore on your own. The sidebar opens each part of your workspace. Home also searches loaded data, documents and reviewed findings. Tutorial **Continue** and **Back** browse all seven introductions without leaving Home. Expand **How to try this step** for details. **Open** takes you to the real workspace page and pauses the introduction; return Home to continue.

2. **Add a file or try a demo — choose your starting point.** For an easy first example, open **Add data → Generate demo**, leave the simple settings as they are and choose **Generate dataset** when you want to create a fictional dataset. Give it a recognizable name, such as “My first practice event.” To use your own file, open **Import data** for CSV/TSV, **Text & PDF** for notes or logs, or **Event JSON** for a supported event record. Review the preview, column meanings, units and quality messages before choosing **Import dataset**, **Save text evidence event** or **Import event JSON**. The import keeps the original file as evidence; any selected repairs apply to the derived copy.

3. **Explore an event — see the evidence and what changed.** Open **Explore an event** and select your dataset. Start with **1 · Your data** to inspect measurements, categories, notes and source information. Move to **2 · What changed** and choose **Run analysis** when you want to calculate the findings. Read the results and quality messages together. A missing channel or uncertain unit may need your attention before you draw a conclusion. **3 · Related guidance** helps connect the event to reference material.

4. **Documents — keep the references behind an answer.** Open **Documents** and expand **Add procedures · PDF, text, or Markdown**. Select a document and record its title and revision. Leave **These files are approved for use as procedural guidance** unchecked for an unapproved reference. Check it only when the source is appropriate and approved for the workspace, then choose **Add files**. Unapproved uploads are retained for reference and excluded from assistant answers. Bundled example procedures are fictional; use them only for practice.

5. **Ask a question — read the sources with the answer.** Open **Ask a question**, enter a plain-language question about an approved document and choose **Search approved documents**. For example: “What checks does this procedure describe before restarting?” Inspect the retrieved excerpts and source identifiers. Answers and drafts use the local AI model with retrieved source context. Model output still needs a person to verify it against the sources; it does not validate an operational decision. If there are no useful sources, add an appropriate approved reference or change the question.

6. **Review & approve — let a person make the decision.** Open **Review & approve**, select the event and, after analysis, choose **Generate new review draft** if you want a draft. Read its evidence, suggestions and source context. A reviewer chooses **Approve**, **Correct** or **Escalate**, enters their **Reviewer full name and role**, adds useful review notes and acknowledges responsibility before choosing **Submit human decision**. Approved or corrected drafts enter the knowledge library; escalated drafts do not. You can continue the tutorial without submitting a decision.

7. **Knowledge library — keep what you learned.** Open **Knowledge library** to find reviewed findings, see who checked them and download a report or record. An empty library is normal until someone has approved or corrected a draft. **Addition items → Try a new demo** offers more fictional examples and expected outcomes; previewing them does not automatically save them to your workspace.

## Come back whenever you need

**Pause** closes the compact guide while keeping your place for the current session. Leaving Home also pauses it. Return to **Home → Continue tutorial** to resume, **Start over** to restart a paused guide, or **Replay tutorial** after finishing. The tutorial has no launchers or panels on other pages. The welcome choice and tour progress belong to this app session and do not create an account or a permanent user preference. A new session can show the welcome invitation again.

Moving through the tutorial does not generate data, save a file, run analysis or approve a draft. Those tasks use the separate application buttons described above. If you hit a connection error, keep the launcher open, open **Addition items → Settings** or **Addition items → System status**, and retry the connection.


Only one FRIB workspace runs at a time for your user, across project copies. The normal launcher you opened most recently has priority; its startup window safely replaces the older FRIB run and controls the new one. Saved records and the shared installed models stay on disk. Check/setup/test commands do not switch the active workspace. FRIB leaves unrelated applications alone, including an unrelated application using a required port. Closing a browser tab does not stop the app. Read **FRIB_Decision_Support/docs/SINGLE_INSTANCE_STARTUP.md** for the full policy.

## Find the compact overview

The sidebar numbers the main pages **1–5**, from **Add data** through **Review & approve**. Open **Addition items** for **System status**, **Settings**, **Help** and **Try a new demo**; one selected section is shown at a time. All previous tools are retained. The interactive **Start tutorial** remains available only on Home.

In Related guidance and Review & save, larger headings separate evidence, suggestions and human decisions. Source bubbles labeled **S1**, **S2**, **S3** open details only when selected. Running requests use bouncing balls, then a checkmark after success. AI waiting bars show a clearly labeled estimated percentage and elapsed time, capped at 95% until a successful response reaches 100%; bulk file jobs show measured percentages and file counts. See **FRIB_Decision_Support/docs/UI_NOVEMBER_UPDATE.md** in the complete project for details.
