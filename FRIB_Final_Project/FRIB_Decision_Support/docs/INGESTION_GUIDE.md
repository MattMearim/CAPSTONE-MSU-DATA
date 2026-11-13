# Import measurements, categories and text

Open **Create Dataset**. The CSV tab accepts mixed columns; the text/PDF tab accepts operator notes, logs and text-based documents. Event JSON import remains available for complete structured captures.

Read the L1/L2 quality panels before saving. They offer explicit derived-copy repairs and unit candidates, then check missing recording intervals, stability and user bounds. See [the data-quality guide](DATA_QUALITY_GUIDE.md) for the deliberately imperfect example and interpretation limits.

## Mixed CSV

1. Upload the file. The preview detects numeric quantities, categories/booleans, text and a possible time column.
2. Confirm the time column and time unit. ISO timestamps can include UTC offsets. Without measured timestamps, the app uses labeled record order and does not calculate durations or frequency spectra.
3. Adjust each column's role: **Numeric**, **Category**, **Log**, or **Ignore**. Rename channels to the expected engineering names when appropriate, such as `vibration`, `cavity_field`, `reflected_power`, `tuner_pressure` or `PLC_STATE`.
4. Confirm source units. They can come from a header such as `pressure [kPa]`, a value such as `1.5 kPa`, a separate per-row unit column, or the selected source-unit setting.
5. Read the standardized preview and any errors. Compatible quantities are stored in one canonical SI unit for their dimension. Then import the file and open **Investigate Event**.

Try `sample_data/mixed_units_and_states.csv`. It combines pressure in Pa/kPa, temperature in C/F/K, PLC categories, boolean states and operator notes. The stored measurements use Pa and K; text stays text.

Numeric blanks are omitted per channel, preserving its actual timestamps. Invalid numeric values and incompatible units are rejected by default with the row and column identified. If explicit skip mode is selected, skipped-cell counts are recorded. No missing measurement is silently replaced with zero. State records capture changes; full category frequencies and the original rows remain available in the import summary and original file.

Large previews show at most 1,000 observed points per numeric channel and the first 1,000 category/text records. Validation still checks the complete file, and import retains all accepted records. Limits are 20 MB, 64 columns, 250,000 rows, 1,000,000 cells and 250,000 total numeric samples.

## Notes, logs and PDF

TXT, Markdown and LOG imports retain every nonempty line as a text record. Consistent ISO or relative timestamps create a measured timeline; otherwise charts explicitly show line order. Explicit severity labels such as `[WARNING]` and `[ERROR]` are retained. Explicit categorical assignments such as `PLC_STATE=RUNNING` also create state changes.

Try `sample_data/operator_shift.log`. It produces a state timeline and text-severity view. Analysis summarizes recorded counts, changes, term mentions and quoted observations. A mention of a fault, including a negated statement, does not become a diagnosed fault.

PDF import extracts selectable text with page references. Scanned images require OCR outside this application. Imported evidence is not automatically treated as an approved operating procedure; use **Files & Documents** for the approval-controlled retrieval library.

## Units and exports

The built-in converter groups compatible units and handles scale and temperature offsets deterministically. Prefix case matters: `mV` and `MV` are different. Absolute temperatures and temperature differences use separate dimensions. Unsupported nonlinear scales such as dBm are rejected rather than treated as ordinary watts.

New known-unit measurements are standardized to SI. Unitless inputs are explicitly labeled dimensionless with a note; the app never infers a physical unit from a signal name. Older captures with missing or unknown units retain their values and show a warning, allowing existing records to remain usable. Assign supported source units when importing physical measurements.

The original upload is preserved byte-for-byte with its SHA-256 checksum. **Original event JSON** preserves the parsed event before application SI standardization, including any explicitly selected repairs; the original source attachment preserves the exact uploaded bytes. Repaired imports also attach a separate reviewed CSV and checksum/change receipt. **Standardized JSON** and **standardized CSV** contain the normalized measurement view. Original uploads are never overwritten by conversion or repair.

## Explore plots

Choose visible measurement channels, a time/record window, category channels and log severity levels. Edit the chart title and display labels in the plot controls. Each measurement has a separate labeled axis with its unit. Categories and text severity use categorical axes. Display labels affect the view; imported channel names determine engineering analysis.

If an event lacks the required RF, mechanical or PLC inputs, the app provides a descriptive mixed-evidence summary and explains which mapping is missing. It does not invent engineering measurements from prose.
