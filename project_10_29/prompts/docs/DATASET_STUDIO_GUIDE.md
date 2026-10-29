# Create Dataset guide

Use **Create Dataset** to generate, import, preview, export and delete event data without editing Python. Start with **Start FRIB.cmd** in the project folder. The launcher starts both services and opens the dashboard; keep its window open and press Ctrl+C there when finished. First-time setup requires Python 3.11+ and internet access. See [START_HERE.md](../START_HERE.md) for startup help.

The page has four tabs:

1. **Generate synthetic dataset**
2. **Import CSV dataset**
3. **Import event JSON**
4. **Dataset library**

## Generate a synthetic event

Choose **RF / SRF**, **Mechanical**, or **PLC / Controls**, enter a dataset name, and adjust the labeled controls. Simple mode shows the main timing and noise settings. Enable **Advanced controls** for sampling and detailed fault parameters. The random seed makes the synthetic noise reproducible.

The optional **Operational context / provenance** fields record cavity, cryomodule, operating mode, beam state, configuration and the person who captured the evidence. Leave unknown fields blank.

Click **Generate dataset**, inspect the signal preview and metadata, then download the event or open it in **Investigate Event**. Normalization changes the visual preview only. Synthetic ground truth is validation metadata, not a diagnosed facility condition.

With Advanced controls enabled, **Save advanced settings as JSON** exports the generator name, seed, dataset name, parameter overrides and entered context. This preset describes generation settings; it is different from a complete event JSON.

## Import a CSV

The CSV importer accepts a table with numeric signal columns. For example:

```csv
time_s,cavity_field,forward_power,reflected_power,tuner_pressure
0.000,1.00,0.91,0.02,1.00
0.001,1.01,0.90,0.02,1.01
0.002,1.00,0.90,0.03,1.01
```

Select the file, inspect the preview, enter a name/domain/event type, then choose the time column and signal columns. Times must be in seconds, finite and strictly increasing. If there is no time column, choose **Generate time from sample rate** and enter the sampling rate in Hz. Enter signal units and operational context where available.

Click **Import dataset**. Selected column names become signal names; the importer does not rename channels or construct discrete state logs. It rejects missing or nonfinite numeric samples and does not silently interpolate evidence. Rename source columns when a domain processor expects a particular channel name.

The original uploaded CSV is preserved as a separate evidence attachment with its filename and SHA-256 checksum. If the event saves but the attachment fails, the dashboard displays a warning: add the original file under **Investigate Event -> Evidence -> Event files** before treating the evidence capture as complete.

## Import an event JSON

Use **Import event JSON** for a previously exported event or a file following [the event schema](../contracts/event.schema.json). The supplied event ID, timestamps, provenance, metadata, signals, states and logs are retained. Existing event IDs cannot be overwritten. The original uploaded JSON is also preserved as an evidence attachment, with the same explicit warning if that separate upload fails.

Use JSON when you need discrete PLC states, logs or per-signal sampling grids. CSV import creates numeric signals; it does not reconstruct those event structures.

## Export formats

- **Event JSON** preserves the complete structured event and is the format for lossless event reimport. Attached original files are downloaded separately in the Evidence tab.
- **Event CSV** is a long table with `kind,name,timestamp_s,value,unit,level,source,message`. Each signal sample keeps its own timestamp; state and log rows are included. This supports unequal sampling grids and avoids pairing one signal with another signal's time axis.
- **Event CSV exports are not the wide numeric-table format accepted by CSV import.** Use event JSON to reopen an exported event, or deliberately transform a long CSV before importing it as a new numeric dataset.
- **Analysis exports** are separate: analysis JSON, feature CSV and timeline CSV are available after Level-2 analysis. Draft and reviewed reports are available in their review/knowledge views.

## Dataset library and evidence files

The library lists event names, IDs, domains, types, signal counts and timestamps. Select an event to inspect its preview or download it. To delete one, select **Confirm delete**, then **Delete dataset**. Deletion removes the event, original evidence attachments, analysis, drafts, reviews and associated knowledge. Audit history remains. Save needed material first.

For individual logs, screenshots or other originals, use **Investigate Event -> Evidence -> Event files**. You can add multiple files, prepare an original download and confirm deletion of one attachment. Deleting an attachment leaves the stored numeric event data in place. Procedure references belong in **Files & Documents**; evidence attachments do not enter assistant retrieval.

## Inputs for Level 2

Select a domain whose processor matches the meaning of the data:

- **RF trip:** `cavity_field`, `reflected_power` and `tuner_pressure`; `forward_power` enables forward/reflected comparison. Optional X-ray and gradient channels support descriptive trends where recognized by the RF processor.
- **Mechanical:** `vibration`; `bearing_temperature` provides an optional overlay.
- **PLC:** discrete states named `PLC_STATE` in a JSON event. Numeric process signals can be included as overlays. The CSV importer does not map a text state column to PLC states.
- **Other / custom:** preserve and preview the data; a custom Level-2 processor requires implementation and registration.

Missing required evidence produces an explanation. Derived alignment, interpolation and spectral assumptions are recorded in the analysis; preserved source files remain unchanged.

## Permanent scenario defaults

Routine experiments use the dashboard controls. To change defaults for subsequent runs, edit the relevant file under `config/scenarios/` and restart FRIB. Settings does not provide a configuration editor. Create a new event for each experiment instead of manually editing stored event JSON.
