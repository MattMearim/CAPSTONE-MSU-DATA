# L1 and L2 data-quality review

The importer reviews the entire source before saving. The quality panel groups blocking errors, review warnings and information, with affected columns, source rows or timestamps and a suggested next step. A warning identifies a condition to investigate; a real equipment event can look like a recording error.

Original-file findings identify physical source rows; after repairs, reviewed-copy findings identify lines in that derived CSV. Repair receipts always refer to the original source rows. L2 locations identify accepted channel sample positions and their recorded timestamps. Reports cap location examples while retaining total counts.

## Try the built-in example

Import `sample_data/quality_review.csv` in **Create Dataset → CSV**. It deliberately includes a duplicate row, a missing-value token, an invalid measurement, a recording gap, a pressure step and constant temperature values.

1. Read the L1 findings. Review the offered duplicate-removal, missing-token and invalid-cell operations. Select only the repairs that match your source records.
2. Preview again. Invalid numeric entries can become missing observations; no replacement measurement is invented. Repair receipts show what changed and identify both source and derived bytes by checksum.
3. Confirm pressure and temperature units. Compatible declarations in headers, cells and per-row unit columns convert to SI. Name-based unit suggestions require confirmation because a name cannot establish a physical scale.
4. In quality expectations, set the expected recording interval to **1 second**. Mark pressure as expected stable only if that is justified, then enter its tolerance and bounds in the displayed stored unit (**Pa**, not kPa). Temperature bounds use **K**; temperature stability tolerances are differences in K.
5. Review the L2 findings and plots, then save. The original uploaded CSV and reviewed derived CSV remain separate downloadable attachments.

## What the checks mean

| Finding | What to review / possible fix |
|---|---|
| Unreadable, binary, bad quoting or malformed CSV rows | Re-export UTF-8 CSV from the source. Explicitly omit individually selected malformed rows only when their loss is acceptable. |
| Duplicate headers or records | Give columns unique names; inspect duplicate records before selecting removal of exact duplicate rows. Conflicting equal-time values require a source decision. |
| Invalid numeric entries, NaN/Inf or missing tokens | Correct from the source, change the column role if it is text, or explicitly mark selected invalid entries missing. Missing values are never zero-filled. |
| Empty measurement cells | Inspect affected source rows and acquisition logs. Available observations remain usable, but omitted observations and any resulting gaps stay visible. |
| Missing/unknown/mixed units | Confirm the sensor configuration. Choose supported source units, map a per-row unit column, or correct unsupported declarations. Compatible mixed units are converted, not averaged. |
| Timestamp order, repeated timestamps or missing timing | Sort a derived copy when appropriate; resolve conflicting equal-time observations manually. Record order alone does not establish elapsed time. |
| Recording gap | With an explicit cadence, the expected recording schedule was not met. With estimated cadence, this is a potential dropout; event-driven or irregular acquisition can be intentional. |
| Flatline / repeated identical values | Check whether the process was stable, the sensor was stuck, or a value was copied forward. Identical readings alone cannot distinguish those cases. |
| Spike, abrupt baseline shift or stability violation | Inspect source samples, units, sensor range and operational logs. The change may be a real event. Do not remove it solely because it triggered a flag. |
| User bounds, absent required channels or unequal coverage | Compare against your declared capture plan and calibrated limits; recover missing evidence from the acquisition system when available. |
| Numerical range / overflow | Confirm units and sensor ranges. If domain calculations exceed finite numeric range, the application retains descriptive evidence and withholds those results. |

Automatic checks do not establish negligence, physical causality, sensor calibration or the correct physical unit for an undeclared number. Bounds, cadence and stable-value expectations come from the user; the application does not assume every process should be stable.

The default estimated-cadence gap factor is 1.8, so a two-interval jump in otherwise regular data is flagged for review. Explicit cadence checks allow 50% timestamp slack and flag intervals at least 1.5 times the declared interval. Adjust expectations to match the acquisition scheme. Stability compares the initial median baseline with the user-set absolute tolerance; it is not a calibrated process model.

## L2 analysis and evidence preservation

Quality reports use the complete accepted capture, even when the preview shows only a sample. Large recording gaps or irregular timing route analysis to a descriptive evidence summary; domain alignment, duration estimates and spectra are withheld to avoid silently interpolating across unrecorded intervals. Plot gaps are display breaks, not new observations.

Saved-event quality checks can be recomputed with new expectations and downloaded without changing the original event. The analysis endpoint also accepts those expectations and records its quality report alongside the result. Import-time expectations and repair receipts remain in event metadata.

The exact original upload is always an attachment with its own checksum. When repairs were selected, pre-standardization event JSON describes the reviewed derived view; use the original source attachment to obtain unchanged bytes. Unit normalization and repair operations never overwrite that attachment. Review report counts and the derived copy before saving.

Scanned PDFs and images still need OCR. Arbitrary corrupted binary content cannot be reconstructed by these checks. Unknown gaps before the first or after the last recorded sample need an external capture schedule to establish that recording was expected there.
