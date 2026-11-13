# Change the AI model

Open **AI settings** directly from the sidebar, or **Addition items → AI settings**.

The compact views are **Main AI**, **Quality agent**, **Library** and **Advanced**. Library accepts future model names or official Ollama links, supports download-and-assign by role, and previews deletion of unused models. Quality agent configures independent read-only data investigation and graph flags, outside RAG. Advanced contains Connection, Hardware and Resources. See [the complete workflow](PRODUCT_WORKFLOW.md) and [quality-agent guide](DATA_QUALITY_AGENT.md).

## Choose a different model — one button

The page opens on **Main AI**. Choose an installed model or a named catalogue choice, then click **Apply model**. Missing catalogue models download automatically; installed models skip the download. The app checks chat and structured JSON before applying the model. No model identifier, address, profile name or terminal command is required. Your explicit choice pauses automatic hardware matching so it stays selected after a restart. Engine selection and Refresh models are in the Engine popover.

The picker includes Qwen3, [Llama 3.2 3B](https://ollama.com/library/llama3.2:3b), [Phi-4 Mini](https://ollama.com/library/phi4-mini:3.8b) and [Gemma 3 4B](https://ollama.com/library/gemma3:4b). Memory-fit indicators are application estimates; compatibility is tested before switching. Any other installed chat model reported by the chosen server also appears. For LM Studio, start its local server and download/load models in LM Studio; this page handles testing and switching. Advanced retains custom model names and server addresses.

## Resource use

A compact **Live resources** strip appears at the top of every workspace page. It polls read-only telemetry about every two seconds directly from the browser, so it continues updating during an AI response or another long task. CPU shows activity, RAM shows computer memory plus approximate app usage, and GPU shows graphics memory plus activity. The model line shows the loaded model's estimated RAM/GPU split or explains that it is unloaded. **Pause / Resume** controls live updates. **Details** opens a dedicated live view with a recent-history graph and tables by app component and model. Hidden tabs stop polling until visible again. Connection failures and missing GPU/model telemetry are shown as unavailable rather than zero use. The compact monitor does not scan files for storage sizes.

Use the sidebar **Live resources** switch to hide or show the strip. The setting persists across navigation and restarts. Hiding removes its iframe and browser polling. **AI settings → Advanced → Resources** shows measured system RAM/CPU, app component RAM/CPU, GPU totals, installed model file sizes, current loaded-model allocations and a storage breakdown. Refresh is automatic every five seconds by default. Installed and loaded are separate: an unloaded model uses disk without an active Ollama model allocation. The selected model may be unloaded while idle and load again when needed.

Ollama allocations come from its `/api/ps` endpoint; non-GPU allocation is the reported total minus GPU allocation. These figures overlap process RAM and device GPU totals and must not be added to them. Process resident RAM can count shared pages more than once. MiniLM runs inside the API process on CPU, so its exact RAM is included in API RAM rather than guessed as a separate process. LM Studio model allocations are shown as unavailable. Storage uses logical file sizes, skips links, and refreshes about once a minute; shared Ollama layers can make individual model sizes overlap.

## Automatic setup — no coding or terminal commands

Select **Main AI → Match my hardware**, or **Advanced → Hardware**. It detects RAM, graphics memory and free disk, then recommends a supported model for this computer. Click **Optimize AI for this computer**. The app starts its bundled engine, downloads missing weights, checks a real answer and structured JSON, and applies the tested model. Measured download progress and the current stage are shown in the UI. Your previous model remains selected until setup succeeds.

Leave **Automatically adapt when my hardware changes** selected to keep this behaviour after an upgrade. Once setup succeeds, the app checks hardware while running (about once a minute) and at the next startup. A changed hardware signature can trigger preparation of a larger or smaller fitting model; transient free-RAM/disk changes alone do not count as a hardware upgrade. Use **Pause automatic matching** to disable future automatic changes without replacing the current model.

Choose **Prefer speed** or **Prefer a larger model** if that matters more than the default balance. **Choose another model size** offers eligible choices without requiring technical model names or server addresses. The advanced provider screen remains optional.

Automatic recommendations use the size-ordered Qwen3 1.7B, 4B, 8B, 14B and 32B family. Explicit alternative-family choices are available in the picker. File sizes come from the vendor's [model library](https://ollama.com/library/qwen3); memory thresholds are conservative application planning estimates, not measured quality or speed guarantees. Larger supported GPUs/RAM unlock larger choices. Unknown hardware, insufficient free space or low currently available RAM blocks a new automatic setup while preserving the existing model.

Setup continues if you navigate away. You can cancel before the final apply step. Cached download bytes are retained, old installed models are kept, and an interrupted setup resumes after restarting the app. A failed compatibility check does not replace the active model. Basic probes do not establish the correctness of every engineering answer.

## Advanced provider and profile controls

Select **Advanced** only when you want to choose your own provider, server, model identifier or saved profile.

1. Choose **Ollama** or **LM Studio** and its local server address.
2. Select an installed model. Use **Refresh models** after loading/downloading a new one. You can also enter its exact identifier.
3. Choose a profile name and press **Test model**. This checks a normal answer and structured JSON, which review drafts require.
4. Press **Save & apply model**. New answers and drafts immediately use that model. No application restart or document reindexing is required. A running evidence request finishes before the switch is committed.

Changing any tested setting requires another test. Successful test receipts expire after ten minutes. Failed tests or failed settings writes leave the active provider unchanged. Existing answers, drafts, reviews and knowledge records retain their original content; new generated records include provider/model provenance.

Ollama is a model runner; the model name selects the weights it uses. When using the bundled server, **Download another Ollama model** streams measured progress and stores assets under `dependencies/ai/models/ollama`. Select **Enter another model name…**, enter the exact model/tag, then choose **Download model**. Refresh and test the model when complete. Interrupted downloads can be resumed by requesting the same model again. When the bundled server is stopped, **Start bundled Ollama** makes it available without a terminal command.

For LM Studio, enable its local API server in LM Studio and load/download the desired model there. The usual address is `http://127.0.0.1:1234/v1`. This integration supports the local server without API-key authentication. LM Studio owns its model storage. The app does not install LM Studio, start it, or stop a server it does not own.

Only HTTP loopback model endpoints are supported here. Cloud services, authenticated endpoints and external hosts need a separate provider/credential implementation; they are not silently routed through a local provider.

The saved chat profiles are in `config/ai-settings.json`. The selected profile overrides the baseline chat section in `config/models.yaml`. Explicit advanced `FRIB_LLM_PROVIDER` / `FRIB_LLM_MODEL` environment overrides still take priority at startup; remove conflicting overrides before selecting a different model through the UI. The supplied private launcher and demo launchers no longer pin a chat provider/model.

Document embeddings remain separate and read-only on this page. Changing MiniLM or its embedding dimensions requires an explicit reindex/migration operation. Selecting a chat model changes neither the embedding fingerprint nor the existing vector index.

Advanced controls expose temperature, request timeout and maximum output tokens. Ollama also receives the chosen context window. For LM Studio, configure the loaded context window in LM Studio itself. Small JSON tests establish basic compatibility, not the quality or correctness of every future answer; human review remains required.
