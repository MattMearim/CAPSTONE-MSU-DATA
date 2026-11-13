# Data Quality Agent and model management

Open **AI settings → Library** to paste a new Ollama model name/tag or official library link. Choose **Main AI**, **Quality agent**, or **Download only**. Download and compatibility checks run in the background. Failed setup keeps the current role assignment. New model identifiers are not limited to the curated recommendation catalogue; they must be supported by the installed model engine.

The same page lists installed models and assigned roles. **Remove model** shows a preview and requires an explicit checkbox confirmation. Main-AI and quality-agent assignments are protected, including a paused quality assignment. To remove an agent model, pause it and remove its assignment, or choose another agent model. Deletion uses Ollama's API, unloads only the unused target, and preserves shared layers used by other models. Actual recovered space can be smaller than the displayed model size. Profile settings are retained and can be reused after reinstalling weights. MiniLM embeddings and user datasets are outside model-library deletion.

## Configure the independent agent

Open **AI settings → Quality agent**. Choose an installed model and click **Test & apply model**, or expand **Get a small model** for one-button setup. This is a separate role: it does not replace the main answer/draft model or document-search embeddings. Local Ollama and LM Studio model assignments are supported. LM Studio model downloads remain managed in LM Studio.

Use the **Enable quality agent** toggle to turn the role on or off without changing the main AI. Off prevents new reviews and discards the result of an in-flight model call when it finishes. Previously saved reports remain available; queued jobs wait until the role is on again. Existing imports, deterministic checks and charts continue to work while the agent is off. Turning it off does not immediately unload model memory; the engine manages its idle timeout.

**Review new datasets automatically** queues a durable SQLite job after evidence is safely stored, including native, CSV/TSV, generated and bulk imports. **Review depth** limits model calls. **Review existing datasets** schedules up to the latest 1,000 datasets; **Run AI quality review** beside an individual graph explicitly reruns it. Queued jobs resume after an application restart. Interactive inference has priority over background agent calls on the same model server, limiting simultaneous model loading on smaller hardware.

## What the model can inspect

This agent does not call RAG, search documents, use embeddings or publish knowledge. Its read-only adapter offers three fixed tools:

- `signal_summary`: channel units, full-channel descriptive bin summaries, and observed extrema samples with real indices.
- `read_window`: up to 96 actual samples from one named channel.
- `compare_dataset`: schema, labels, units and descriptive ranges from another recent, explicitly listed dataset.

There is no SQL-generation, file-system, code-execution, database mutation or repair tool. Labels, metadata and logs are treated as untrusted data. Summaries do not themselves classify spikes: the model proposes categories, suspicious points/regions and further checks. Existing deterministic Pydantic/format/unit/time checks remain available.

Context and calls are bounded. Reports show directly inspected sample counts, summarized channels, requested windows and compared dataset IDs. Large datasets may only receive a partial review. No findings is not an integrity certificate. Model confidence is self-reported and uncalibrated. A real physical transient can be flagged as suspicious, and a small model can miss corruption.

## Flags, review and corrections

Open a dataset in **Explore an event → Evidence**. The **Data Quality Agent** panel shows progress, coverage, findings and read-only investigation details. Pending jobs refresh the panel and chart automatically.

Purple crosses and bands identify **AI quality proposals**; deterministic flags retain their existing appearance. Numeric endpoints must reference samples actually shown to the model, and numeric findings must cite exact inspected index/value pairs. Python resolves real timestamps/values and rejects unknown channels, invented/out-of-range/unseen indices, claimed raw values that disagree with the samples, and unsupported repair actions. Summary/bin averages are not accepted as raw-value evidence. These checks ground coordinates and quoted evidence; they do not establish that an AI interpretation is correct. Dismissing a finding removes its AI overlay; accepting it records a review without changing measurements.

The agent can propose review-only checks, replacement of a single inspected sample, exclusion of a directly inspected bounded interval, or a display-label correction. To execute a proposal, a named reviewer must accept the flag, confirm the exact proposal, and click **Create corrected copy**. Python revalidates finite numbers, schemas, sample lengths and strict time order, and runs quality checks again. This validates structure, not the physical correctness of an inferred replacement. Source confirmation remains the reviewer's responsibility.

Repairs create a new event ID and preserved JSON/checksum; the original event and source files remain unchanged. Repeated submission of the same approved repair returns the same copy. Stale source fingerprints and changed proposal hashes are rejected.

L1/L2 import reports also offer **Explain these issues with the Data Quality Agent**. This provides a bounded explanation and suggested checks, without applying changes.

## Persistence and audit

Quality role settings live in `config/quality-agent.json` (or the configured isolated preference root). SQLite's `quality_agent_runs` stores jobs, model identity, normalized source fingerprints/provenance, coverage, model responses, read-tool traces, findings, proposed repairs and review state. The audit table records queueing/completion/failure, reviewer decisions, role settings, model installation/deletion and corrected-copy receipts/checksums. The model itself cannot write these records; Python commits them.

Event deletion removes its quality reports. Workspace reset removes quality jobs/reports alongside other content. In-flight jobs recheck record existence and cannot repopulate deleted/reset evidence. This remains the local SQLite deployment; PostgreSQL migration and multi-user administrator permissions are separate work.
