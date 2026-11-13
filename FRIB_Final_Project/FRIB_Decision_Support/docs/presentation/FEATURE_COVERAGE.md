# L1/L2 feature and evidence inventory

This inventory describes the current local implementation, its test assertions and its demonstration boundaries. It is not a claim of live FRIB commissioning or physical causal accuracy. Execution results belong to the generated JUnit report and demonstration manifest; a test reference below identifies coverage, not an assumed passing result.

## Reading the evidence

Complete setup with **Start FRIB.cmd**, then copy **Active interpreter** from **System & upgrades → Hardware details** and stop FRIB before installing development packages. From the project root, replace the placeholder below with that exact path. A retained `.venv` may be inactive after an upgrade; refresh this path after further upgrades.

```powershell
$fribPython = 'C:\paste\the\active\python.exe'
& $fribPython -m pip install -e ".[dev,ui]"
& $fribPython -m pytest --junitxml=presentation_evidence\pytest.xml -q
& $fribPython scripts/run_l1_l2_demo.py --output presentation_evidence\demo
```

Use a fresh demonstration output directory for a new evidence run. The runner writes a machine-readable scenario manifest, per-scenario expected/observed checks, reusable inputs and native event/analysis JSON. Inspect failed checks before using an artifact in a presentation. See [PRESENTER_GUIDE.md](PRESENTER_GUIDE.md) for the live sequence and API alternatives. Delivered records are `C:\Users\berda\OneDrive\Documents\FRIB\deliverables\L1_L2_Presentation\evidence\scenario_results.json` and `pytest-results.xml`; the adjacent `Feature_Showcase.html` presents their actual contents offline.

The tables use these test-file aliases. `Alias::test_name` expands to the exact pytest function selector `tests/<file>.py::test_name`. Parameterized functions have additional case IDs in JUnit; the base selector runs every parameter case.

| Alias | Exact file | Evidence level |
|---|---|---|
| `IG` | `tests/test_ingestion.py` | Pure parser/model assertions |
| `UQ` | `tests/test_upload_quality.py` | Raw L1 inspector and explicit repair helper assertions |
| `EQ` | `tests/test_event_quality.py` | Pure L2 quality assertions |
| `UN` | `tests/test_units.py` | Deterministic unit conversion assertions |
| `MX` | `tests/test_mixed_api.py` | FastAPI integration with isolated storage |
| `QA` | `tests/test_quality_api.py` | L1/L2 API, preservation and analysis gates |
| `QU` | `tests/test_quality_ui.py` | Streamlit AppTest and plot-helper assertions; selected tests use the actual API |
| `DU` | `tests/test_dashboard_ui.py` | Streamlit AppTest with a test backend |
| `PR` | `tests/test_processing_robustness.py` | Analytical domain/helper assertions |
| `PT` | `tests/test_processing.py` | Three synthetic-domain analysis checks |
| `EP` | `tests/test_evidence_processing.py` | Descriptive fallback/contract assertions |
| `AL` | `tests/test_api_lifecycle.py` | API persistence, attachments, restart and deletion |
| `IN` | `tests/test_integrity.py` | Model/generator safety and integrity |
| `GE` | `tests/test_generators.py` | Synthetic generators |
| `ST` | `tests/test_startup.py` | CLI/configuration startup |
| `PL` | `tests/test_preview_limits.py` | Whole-file validation versus sampled preview |
| `DI` | `tests/test_distribution.py` | Extracted portable source workflow |
| `SH` | `tests/test_showcase_distribution.py` | Offline evidence-presentation integrity |

“UI tested” means AppTest exercises widgets/state and assertions. It does not mean every screen has been visually inspected in a browser, every platform was tested, or every underlying detector was separately driven through the UI. “Helper only” identifies a callable capability without a dedicated user-facing control.

Source/reference audit: all 224 concrete test references in this inventory resolve to 163 existing pytest functions. All 30 statically declared L1 issue codes and 21 statically declared L2 issue codes were checked against the tables; dynamically selected L1 incompatible_units/invalid_numeric, L2 RECORDING_GAP/POTENTIAL_RECORDING_GAP, and the processing registry's NUMERICAL_RANGE are also listed. These are inventory/reference checks, not execution totals, branch coverage or a measured code-coverage percentage.

## L1 acquisition, contracts and evidence management

| Implemented feature | Where / boundary | Exact test selectors |
|---|---|---|
| Event contract | Schema version, ID, domain/type, capture timestamp, metadata, signals, states, logs, attachments and provenance. Signal samples must be finite, equal length, at least two, strictly increasing; channel names and filesystem-safe IDs are checked. | `IN::test_invalid_samples_rejected`; `IN::test_unsafe_event_id_rejected`; `IN::test_duplicate_signals_rejected`; `EP::test_booleans_cannot_be_silently_coerced_to_numeric_samples` |
| Operational context | UI fields Cavity, Cryomodule, Operating mode, Beam state, Configuration / settings, Captured / imported by. Unknown fields can stay blank. Arbitrary input metadata is retained in the event. | `IG::test_mixed_csv_preserves_measurements_categories_logs_and_provenance`; `DU::test_generator_preserves_simple_controls` exercises simple generator controls, not every context field individually |
| RF synthetic generator | Cavity field, forward/reflected power, tuner pressure, RF/beam states and source logs; editable timing/noise/rate/duration/decay parameters, seed and synthetic provenance. Normalized signals are dimensionless demonstration values. | `GE::test_three_domains_generate`; `GE::test_custom_generator_overrides_are_applied`; `PT::test_rf_ground_truth_timing` |
| Mechanical synthetic generator | Vibration plus bearing temperature, alarm state and log; base/fault frequency, amplitude, onset, noise, duration and rate. | `GE::test_three_domains_generate`; `PT::test_mechanical_fault_frequency` |
| PLC synthetic generator | Process sensor, RUNNING/WARNING/INTERLOCKED/RESET_PENDING states and source logs; warning/interlock/reset timing and rate/duration. | `GE::test_three_domains_generate`; `PT::test_plc_sequence` |
| Generator bounds | Finite parameters; known override keys; positive durations/rates; 4–250,000 samples per signal; rate at most 100,000 Hz; nonnegative noise; positive decay; frequencies below Nyquist; ordered scenario times. | `IN::test_generator_rejects_unbounded_or_invalid_parameters`; `GE::test_custom_generator_overrides_are_applied`; not every individual bound has a distinct pytest assertion |
| Standalone generation / launch | `scripts/generate_event.py` produces JSON without initializing AI; `--output` uses exclusive creation; optional `--store`. Launcher checks/configuration resolve outside project cwd. | `ST::test_standalone_generator_needs_no_ai_provider`; `ST::test_configuration_works_outside_project_folder`; `ST::test_launcher_check_from_other_folder`; `DI::test_extracted_source_distribution_supports_complete_workflow` |
| Complete event JSON | Structured `/events` import preserves supplied ID/provenance and source attachment through the UI. Duplicate IDs return conflict instead of replacing evidence. | `DU::test_json_import_preserves_supplied_id_provenance_and_original_bytes`; `AL::test_event_original_attachments_review_and_cascade_delete`; `MX::test_duplicate_import_preserves_first_capture_and_original` |
| CSV encodings / delimiters | UTF-8/BOM; comma, semicolon, tab or pipe sniffing; quoted text and multiline cells. Unique, nonempty headers. Arbitrary broken quoting is blocked by quality inspection. | `IG::test_delimiter_bom_and_explicit_source_target_units`; `IG::test_invalid_csv_is_actionable`; `UQ::test_bad_quotes_remain_blocked_even_with_skip_invalid_selected`; `UQ::test_explicit_measurement_repairs_preserve_text_originals_and_checksums` |
| Column roles | Measurement, Category / state, Text / log message, Ignore; channel/category renaming and per-row unit-column mapping. Text is not silently converted into a measurement or diagnosis. | `IG::test_mixed_csv_preserves_measurements_categories_logs_and_provenance`; `IG::test_explicit_numeric_role_rejects_arbitrary_text_and_skip_is_counted`; `DU::test_mixed_csv_mapping_keeps_categories_logs_and_per_row_units`; `DU::test_actual_mixed_parser_reaches_valid_preview_and_preserves_plc_name` |
| CSV timing | s, ms, us, ns, min, h, ISO datetime and explicit row order; suffix time_ms/us/ns; chronological derived records retain source-row references. Numeric blanks retain each channel's actual timestamps. | `IG::test_time_header_suffix_infers_real_scale`; `IG::test_datetime_csv_sorted_without_losing_original_row_provenance`; `IG::test_blank_samples_keep_each_channels_actual_timestamps`; `DU::test_csv_import_preserves_original_and_does_not_interpolate` |
| Categories / booleans | Initial values and subsequent changes become StateEvent records; repeated original values remain represented in full row-frequency summaries and original bytes. True/false remain categories. | `IG::test_mixed_csv_preserves_measurements_categories_logs_and_provenance`; `EP::test_categorical_events_are_chronological_and_never_numeric_samples`; `DU::test_mixed_csv_mapping_keeps_categories_logs_and_per_row_units` |
| Text / logs / Markdown | Every nonempty line becomes a log; explicit severity aliases; explicit categorical name=value assignments also create state changes. Consistent relative or ISO time is used; mixed/missing time is labeled ordinal. | `IG::test_narrative_relative_time_explicit_states_and_severity`; `IG::test_datetime_narrative_anchors_real_timing_and_orders_states`; `IG::test_narrative_missing_or_mixed_timestamps_uses_honest_row_coordinates`; `IG::test_unlabelled_prose_is_not_misread_as_relative_time_or_state`; `DU::test_text_only_import_and_record_order_plot` |
| Selectable-text PDF | Text extraction with source page/line metadata, 500-page and extracted-text limits. Blank/unreadable/encrypted PDF errors; no OCR or visual/table interpretation. | `IG::test_text_pdf_extracts_evidence_with_page_provenance`; `IG::test_unreadable_pdf_has_friendly_error`; `IG::test_pdf_extracted_text_limit_is_actionable`; `AL::test_pdf_original_and_blank_pdf_validation` |
| Reject versus explicit skip | Default rejects invalid numeric/time entries. Selected skip mode omits invalid timestamps as rows and invalid numeric cells per channel, retaining counts. No fill, interpolation or invented time. Declared unsupported units remain blockers. | `IG::test_explicit_numeric_role_rejects_arbitrary_text_and_skip_is_counted`; `UQ::test_skip_policy_warns_about_skippable_cells_and_time_but_blocks_insufficient_capture`; `UQ::test_skipped_invalid_time_cannot_define_units_for_accepted_numeric_rows` |
| Whole-file limits / preview | 20 MiB upload, 64 columns, 250,000 rows, 1,000,000 cells; parser also caps combined numeric/state/log records. Display preview at most 1,000 points per channel and first 1,000 state/log records, after complete validation/quality checks. | `IG::test_upload_and_record_limits_reject_before_persistence`; `UQ::test_upload_and_cell_bounds_stop_assessment_and_repair`; `PL::test_sampling_preview_does_not_truncate_the_import`; `PL::test_invalid_final_row_cannot_hide_outside_sampled_preview`; `QA::test_whole_file_quality_is_computed_before_preview_sampling` |
| Exact originals / provenance | SHA-256 identifies actual source bytes. Parsed event before SI conversion, standardized JSON/CSV and exact source attachment are distinct. A repaired import additionally retains reviewed CSV and receipt. | `MX::test_import_preserves_exact_source_and_separates_raw_from_si_exports`; `QA::test_explicit_shape_repair_is_previewed_and_preserves_original`; `AL::test_event_original_attachments_review_and_cascade_delete`; `DU::test_event_exports_use_original_and_standardized_backend_routes` |
| Add/download/delete evidence | Event attachments support multiple evidence files, sizes/checksums/time; attachment deletion leaves event samples intact. Dataset deletion cascades analysis/drafts/knowledge/files and persists across restart. | `AL::test_attachment_delete_does_not_change_original_event`; `AL::test_event_original_attachments_review_and_cascade_delete`; `MX::test_text_only_rf_evidence_has_full_review_lifecycle_and_restart_delete`; `DU::test_event_deletion_clears_event_and_file_cache` |
| Reference files | Separate Files & Documents library; upload/download/delete and approval metadata. Evidence attachments do not enter approved retrieval automatically. L3 answer accuracy is outside this L1/L2 demonstration. | `AL::test_approved_original_index_and_deletion_survive_restart`; `AL::test_unapproved_original_remains_outside_retrieval`; `DU::test_multiple_document_uploads_default_to_unapproved`; `DU::test_document_delete_requires_confirmation_and_clears_answers` |

## Units: complete supported families

Every catalog entry is round-trip checked by `UN::test_catalog_is_independent_and_every_entry_round_trips`. Representative scale/offset cases are parameterized in `UN::test_supported_physical_conversions`; alias/prefix cases use `UN::test_normalization_preserves_prefix_case`. API conversion is tested by `MX::test_unit_catalog_and_offset_conversion`, and the compatible-dimension UI by `DU::test_unit_converter_uses_dimension_compatible_units`.

| Dimension | Supported canonical labels / scales | Meaning and boundary |
|---|---|---|
| Time | s, ms, us, ns, min, h | Canonical s; microsecond aliases µs/μs. |
| Frequency | Hz, kHz, MHz, GHz | Canonical Hz. |
| Voltage | V, mV, kV, MV | Canonical V; mV and MV are distinct. |
| Gradient | V/m, kV/m, MV/m | Canonical V/m. |
| Power | W, mW, kW, MW | Canonical W; no nonlinear dBm conversion. |
| Pressure | Pa, kPa, MPa, bar, mbar, Torr, mTorr, psi | Canonical Pa; fixed registered factors. |
| Length | m, cm, mm, um | Canonical m; micrometre aliases. |
| Acceleration | m/s^2, g | Canonical m/s^2; standard gravity factor. |
| Velocity | m/s, mm/s | Canonical m/s. |
| Absolute temperature | K, C, F | Canonical K; scale and offset conversion. |
| Temperature difference | delta_K, delta_C, delta_F | Canonical delta_K; scale only, no absolute-temperature offset. |
| Dimensionless | 1, % | Canonical 1; fraction/normalized/unitless aliases. |
| Count rate | counts/s | cps/count/s aliases; distinct from Hz in dimensional checking. |

Additional assertions: quantity suffix overrides defaults (`UN::test_quantity_parser`); reject nonmeasurements/NaN/Inf/overflow (`UN::test_non_measurements_are_rejected`, `UN::test_conversion_overflow_is_rejected`); reject unknown/incompatible units (`UN::test_unknown_units_are_actionable`, `UN::test_incompatible_dimensions_are_rejected`); deep-copy/idempotent SI normalization preserves original labels and legacy unknown-unit warnings (`UN::test_event_conversion_preserves_original_and_documents_warnings`, `UN::test_event_conversion_is_idempotent_and_keeps_original_units`). Absolute versus difference temperature is explicitly checked in `UN::test_temperature_differences_have_no_offset_and_names_do_not_infer_units`.

Headers, quantity suffixes and per-row labels are measurements of the source convention, not name guesses. Compatible mixed scales convert; conflicting dimensions fail. Missing units stay unitless with warnings. Unsupported explicit declarations such as dBm stay visible and require an explicit correction (`IG::test_unsupported_declared_unit_is_preserved_in_preview_and_requires_override`). Legacy missing/unknown labels are preserved on read, with warnings (`QA::test_legacy_view_uses_same_units_as_quality_without_rewriting_storage`).

L1 suggestions remain unassigned: explicit unit evidence is high confidence, a supported name suffix is medium, and physical-name candidates are low. Temperature names offer C/K/F, and difference names delta_C/delta_K/delta_F; value ranges do not establish an offset scale. Name families cover pressure/vacuum, voltage, temperature, gradient, power, frequency, acceleration and length. Assertions: `UQ::test_temperature_names_produce_ambiguous_candidates_without_offset_guessing`, `UQ::test_name_suffix_and_ambiguous_names_remain_unassigned_candidates`, `QA::test_unit_suggestions_do_not_assign_an_unconfirmed_physical_unit`, `QU::test_unit_hints_require_manual_source_assignment`.

## L1 issue-code inventory

Raw assessment can collect several issues from one corrupt CSV; strict parsing is unchanged. Errors block import, warnings request review, info describes limitations. Counts cover the inspected capture, while row/time examples cap at 25. Source rows are physical record-start lines; receipts also include end_row for multiline records. Reviewed-copy row numbers can change after repair.

| Code | Condition | Direct pytest assertion or explicit coverage boundary |
|---|---|---|
| `invalid_upload` | Unsupported/unsafe/empty/oversize upload | `UQ::test_unreadable_or_incomplete_csv_returns_flags_not_exceptions`; `UQ::test_upload_and_cell_bounds_stop_assessment_and_repair`; parser filename/type cases: `IG::test_upload_validation` |
| `unreadable_text` | UTF-8/binary failure | `UQ::test_unreadable_or_incomplete_csv_returns_flags_not_exceptions` |
| `empty_header` | Missing header names | Same parameterized UQ selector |
| `duplicate_headers` | Ambiguous repeated names | Same parameterized UQ selector |
| `column_limit` | More than 64 headers | Implemented branch; no dedicated L1-code pytest assertion identified. Runner boundary evidence is required before claiming direct demonstration. |
| `inspection_limit` | Row/cell inspection bounds | `UQ::test_upload_and_cell_bounds_stop_assessment_and_repair` |
| `row_shape` | Wrong field count | `UQ::test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems`; `QA::test_malformed_file_receives_actionable_review_and_never_writes` |
| `empty_file` | Decoded CSV has no record, e.g. BOM-only | Implemented branch; empty-byte tests instead assert invalid_upload. |
| `csv_syntax` | Bad quote/truncated record | `UQ::test_bad_quotes_remain_blocked_even_with_skip_invalid_selected`; `UQ::test_unreadable_or_incomplete_csv_returns_flags_not_exceptions` |
| `no_data_rows` | Header without evidence | Parameterized unreadable/incomplete UQ selector |
| `possible_truncation` | Final short row without newline | `UQ::test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems`; explicitly a structural clue, not proof of loss |
| `invalid_options` | Malformed mappings/metadata | `UQ::test_malformed_mapping_options_are_reported`; `MX::test_malformed_import_settings_write_nothing` |
| `duplicate_rows` | Exact parsed fields repeat | `UQ::test_bounded_details_retain_exact_issue_and_repair_counts`; `UQ::test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems` |
| `unsupported_time_unit` | Time header has non-time/unknown declaration | Parser guard: `IG::test_time_header_cannot_silently_discard_non_time_unit`; no dedicated L1-code assertion identified |
| `time_unit_unconfirmed` | Bare time numbers without selected scale | `UQ::test_unlabelled_time_unit_is_flagged_and_can_be_explicitly_confirmed` |
| `duplicate_timestamps` | Equal source timestamps | `UQ::test_duplicate_timestamp_only_blocks_numeric_channels_with_duplicate_samples`; ties in disjoint sparse channels are warnings |
| `time_reversal` | Source order moves backward | `UQ::test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems`; stable sort is optional |
| `invalid_timestamp` | Missing/unreadable time | `UQ::test_skip_policy_warns_about_skippable_cells_and_time_but_blocks_insufficient_capture`; `UQ::test_skipped_invalid_time_cannot_define_units_for_accepted_numeric_rows` |
| `inferred_time` | Ordinal positions instead of measured timing | CSV ordinal behavior: `IG::test_missing_units_are_dimensionless_without_physical_inference`; narrative limitation uses document_limitation. No dedicated assertion of this exact CSV L1 code identified. |
| `missing_cells` | Blank source fields | `UQ::test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems` |
| `unsupported_unit` | Unknown header/cell/selected unit | `UQ::test_unit_declarations_conflicts_and_mixed_prefixes_are_visible` |
| `missing_tokens` | NA/N/A/NULL/NaN-style strings | `UQ::test_all_placeholder_column_is_reviewed_without_assuming_a_numeric_role`; `UQ::test_skip_policy_warns_about_skippable_cells_and_time_but_blocks_insufficient_capture` |
| `nonfinite_values` | NaN/Infinity-style invalid measurement | `UQ::test_sentinels_are_flagged_without_deleting_or_reinterpreting_real_numbers` |
| `mixed_numeric_text` | Text among possible measurements | `UQ::test_mixed_numeric_text_unmapped_is_reviewed_without_reclassifying_prose` |
| `possible_sentinel` | Registered common sentinel-like values | `UQ::test_sentinels_are_flagged_without_deleting_or_reinterpreting_real_numbers`; real values stay intact |
| `incompatible_units` | Conflicting physical dimensions | `UQ::test_unit_column_dimension_conflict_is_not_hidden_by_cell_suffix`; `UQ::test_unit_declarations_conflicts_and_mixed_prefixes_are_visible` |
| `invalid_numeric` | Numeric-shaped but invalid finite range | Units layer rejects 1e999 in `UN::test_non_measurements_are_rejected`; no dedicated L1-code assertion identified |
| `insufficient_numeric_samples` | Fewer than two accepted distinct-time samples | `UQ::test_skip_policy_warns_about_skippable_cells_and_time_but_blocks_insufficient_capture` |
| `missing_unit` | Bare physical numbers lack unit evidence | `UQ::test_name_suffix_and_ambiguous_names_remain_unassigned_candidates`; `QA::test_unit_suggestions_do_not_assign_an_unconfirmed_physical_unit` |
| `mixed_unit_scales` | Compatible explicit labels have different scales | `UQ::test_per_row_units_detected_without_missing_unit_guess`; `UQ::test_unit_declarations_conflicts_and_mixed_prefixes_are_visible` |
| `document_limitation` | PDF/text extraction or ordinal-time caution | `UQ::test_narrative_assessment_exposes_timing_limits_and_refuses_csv_repairs` |
| `unreadable_document` | Narrative/PDF extraction cannot proceed | Parser assertions: `IG::test_unreadable_pdf_has_friendly_error`; no dedicated L1-code assertion identified |

## All explicit repair operations

Repairs act on a derived CSV and require a user selection. No operation infers units, edits timestamps, interpolates, fills zeroes, or reconstructs missing observations. `operation` is the canonical key; `action` is a compatible alias. Conflicting or unsupported parameters fail.

| Operation | Exact behavior / selection boundary | Test selectors |
|---|---|---|
| `drop_exact_duplicate_rows` | Retain first exact parsed-field record; optionally restrict to selected redundant source rows. Do not collapse merely similar rows. | `UQ::test_bounded_details_retain_exact_issue_and_repair_counts`; `UQ::test_repairs_are_idempotent_and_keep_blank_records_and_text` |
| `sort_by_time` | Stable sort of complete remaining records using valid measured time. No subset sort, invented times or automatic duplicate-time resolution. | `UQ::test_cell_selection_uses_original_physical_rows_after_sorting`; `UQ::test_unit_errors_and_unreadable_timestamps_cannot_be_repaired_by_deletion_or_guessing` |
| `mark_missing_tokens` | Recognized NA/N/A/NULL/NAN/+NAN/-NAN/NONE/MISSING/#N/A tokens become blank in confirmed numeric measurement columns. Optional selected rows; categorical/text meanings remain untouched. | `UQ::test_explicit_measurement_repairs_preserve_text_originals_and_checksums`; `UQ::test_repairs_are_idempotent_and_keep_blank_records_and_text`; `QA::test_invalid_measurements_can_be_marked_missing_without_touching_notes` |
| `drop_malformed_rows` | Only explicitly selected physical records with wrong field counts may be excluded. Bad quotes/encoding and valid rows are not guessed away. | `QA::test_explicit_shape_repair_is_previewed_and_preserves_original`; `UQ::test_unsupported_ambiguous_or_unselected_repairs_are_rejected` |
| `drop_invalid_numeric_cells` | Explicit selected rows plus numeric columns; invalid text/nonfinite values become blank. Valid finite values and sentinel-like real numbers remain; unsupported/incompatible units cannot be hidden by deletion. | `UQ::test_sentinels_are_flagged_without_deleting_or_reinterpreting_real_numbers`; `UQ::test_unit_errors_and_unreadable_timestamps_cannot_be_repaired_by_deletion_or_guessing`; `QA::test_invalid_measurements_can_be_marked_missing_without_touching_notes` |

Cross-cutting repair evidence: exact source/derived SHA-256, counts, physical source start/end rows, at most 25 example locations, idempotent no-op bytes, BOM/delimiter/line-ending and untouched text/blank-record preservation. Tests: `UQ::test_explicit_measurement_repairs_preserve_text_originals_and_checksums`, `UQ::test_repairs_are_idempotent_and_keep_blank_records_and_text`, `UQ::test_cell_selection_uses_original_physical_rows_after_sorting`, `UQ::test_bounded_details_retain_exact_issue_and_repair_counts`. UI consent and repreview are exercised by `QU::test_source_quality_visible_and_repair_never_selected_automatically`, `QU::test_explicit_repair_repreviews_and_imports_identical_selection`, `QU::test_invalid_explicit_repair_rows_cannot_be_saved`, `QU::test_actual_quality_api_repair_reaches_reviewed_si_preview`.

## L2 numerical processing and presentation

| Implemented feature | Behavior and boundary | Exact tests |
|---|---|---|
| Adapter cleaning helper | Copy finite samples, stable sort and average equal-time samples; record removals/reordering/averaging/rates/irregularity. **Helper only:** strict imports do not automatically perform this averaging. | `PR::test_cleaning_records_each_transformation_without_editing_source` |
| Shared interval alignment | Uniform linear overlay grid within true common interval, default fastest timestamp-derived rate; no extrapolation. Metadata records each source and warns about rate mismatch/upsampling/downsampling without anti-alias filtering. | `PR::test_alignment_uses_common_interval_and_preserves_evidence`; `PR::test_nonoverlapping_captures_have_actionable_error`; rate warnings also `PR::test_mechanical_spectrum_uses_timestamps_and_native_bandwidth`. Empty/invalid-rate/1,000,000-output guards are implemented without separate dedicated test assertions identified. |
| FFT | Mean removal, configurable window (default Hann), single-sided coherent-gain-corrected amplitude, Hz bins, original amplitude unit, native timestamp-derived uniform resampling and resolution metadata. Constant/short captures return missing estimates/warnings instead of invented peaks. | `PR::test_fft_frequency_and_amplitude_match_known_sine`; `PR::test_mechanical_spectrum_uses_timestamps_and_native_bandwidth`; `PR::test_constant_vibration_has_no_invented_dominant_frequency`; `PR::test_short_prepost_capture_returns_missing_estimates_and_warnings` |
| RF trip analysis | Required cavity_field/reflected_power/tuner_pressure; earliest active interlock, otherwise steepest field-decline reference; chronological source timeline; pre/post pressure windows and delta; event-window reflected peak; approximate first 1/e field crossing on actual timestamps; pretrip FFT. Reference and limits are explicit. | `PT::test_rf_ground_truth_timing`; `PR::test_rf_decay_uses_actual_timestamps_and_first_chronological_interlock`; `PR::test_short_prepost_capture_returns_missing_estimates_and_warnings`; `PR::test_missing_required_signal_explains_column_mapping` |
| RF optional power comparison | Optional forward_power adds pre-event forward/reflected means and ratio only for positive forward mean and identical units. Aligned full/pre/post plots retain units. No physical cavity-parameter fit or cause classifier. | Exercised by synthetic RF processing; no direct numerical ratio assertion identified in existing pytest functions. Runner assertion must be consulted for the concrete comparison demonstration. |
| X-ray/gradient trends | xray/x_ray/xray_rate/x_ray_rate plus gradient/cavity_gradient aliases; aligned peaks/means/range/correlation and scatter. Works alone or as optional RF addition. Descriptive correlation only. | `PR::test_field_emission_trends_are_descriptive_and_use_units`; `DU::test_analysis_renders_field_emission_and_state_timeline`; `tests/test_hypotheses.py::test_optional_field_emission_pattern_does_not_claim_diagnosis` |
| Mechanical | Vibration plus optional bearing_temperature; earliest active alarm or maximum absolute measured vibration reference; native pre/post RMS; post-event frequency/amplitude and aligned temperature overlay. | `PT::test_mechanical_fault_frequency`; `PR::test_mechanical_spectrum_uses_timestamps_and_native_bandwidth`; `PR::test_constant_vibration_has_no_invented_dominant_frequency` |
| PLC sequence | Chronological PLC_STATE sequence; all transition intervals, including repeated pairs; first INTERLOCKED; configured expected ordered subsequence; incomplete-capture warnings; state plot and optional numeric alignment. | `PT::test_plc_sequence`; `PR::test_plc_sorts_states_and_retains_repeated_transition_intervals`; `PR::test_plc_incomplete_sequence_is_flagged_without_inventing_states` |
| Descriptive mixed fallback | Per-channel finite min/max/mean/first/last/native times; categorical event counts/changes; severity counts, term mentions and source excerpts; category/log timelines. Text does not become a physical diagnosis. | `EP::test_text_only_capture_is_described_without_claiming_a_cause`; `EP::test_categorical_events_are_chronological_and_never_numeric_samples`; `EP::test_unrelated_measurements_keep_native_times_and_explicit_units`; `EP::test_summary_mean_stays_finite_for_large_finite_values`; `MX::test_text_only_rf_evidence_has_full_review_lifecycle_and_restart_delete` |
| Domain readiness / timing gate | Missing required domain channels, unknown domains or ordinal timing use descriptive fallback. Recording gaps/irregular cadence/invalid values or timestamps withhold domain alignment, duration estimates and FFT. | `EP::test_unknown_timing_never_produces_spectral_or_duration_estimates`; `QA::test_domain_analysis_does_not_interpolate_through_recording_gap`; `MX::test_text_only_rf_evidence_has_full_review_lifecycle_and_restart_delete` |
| Numeric overflow gate | Finite source values can overflow domain math; withhold result, retain evidence, emit NUMERICAL_RANGE and finite descriptive fallback. | `QA::test_extreme_finite_values_cannot_persist_nonfinite_domain_results` |
| Plot explorer / units | Numeric channels use independent axes, original timestamps and explicit units. Category/state/log severity filters, view window, editable title/display labels and normalized view affect display only. | `DU::test_signal_plot_labels_units_and_independent_axes`; `DU::test_explorer_filters_and_editable_display_labels`; `DU::test_text_only_import_and_record_order_plot`; `QU::test_normalized_plot_remains_finite_for_extreme_recorded_values` |
| Display gaps / sampled preview | Break lines across detected intervals without creating observations. Full captures detect every gap even beyond report's 25 examples; downsampled previews do not infer gaps from display spacing. Ordinal coordinates never acquire measured-time claims. | `QU::test_quality_plot_breaks_missing_interval_without_changing_samples`; `QU::test_full_capture_breaks_all_gaps_beyond_bounded_report_examples`; `QU::test_downsampled_preview_uses_full_report_intervals_not_display_spacing`; `QU::test_ordinal_coordinates_do_not_infer_timing_gaps` |
| Read-only quality / persisted analysis | Recompute quality against operator expectations without changing saved evidence. Analysis reuses submitted/import expectations and records quality in result. Import source/reviewed reports and receipt remain distinguishable. | `QA::test_custom_quality_expectations_are_read_only_and_reused_in_analysis`; `QU::test_saved_quality_controls_submit_si_expectations_once_and_download`; `QU::test_saved_original_and_repaired_quality_are_distinguished` |

## Every L2 quality issue code

L2 locations are 1-based accepted-sample positions plus recorded timestamps, not original CSV line numbers. The checks report observations; unusual values can be real process events. Bounds and tolerances use stored SI units; temperature tolerance is a difference in K, not an offset absolute reading.

| Code | Trigger / interpretation | Exact selector |
|---|---|---|
| `MISSING_CHANNEL` | User-required numeric/state name absent | `EQ::test_required_channels_and_skipped_cells_report_known_counts` |
| `UNMATCHED_EXPECTATION` | Channel-specific settings name absent evidence | `EQ::test_unmatched_channel_expectations_are_not_silently_ignored` |
| `NO_NUMERIC_SIGNALS` | State/text-only capture; numeric checks skipped (info) | Text-only API/fallback tests exercise this route; no standalone assertion of this exact code identified |
| `UNSPECIFIED_UNIT` | Legacy blank unit preserved | `EQ::test_missing_or_unknown_units_are_preserved_without_inference` |
| `UNKNOWN_UNIT` | Unsupported legacy unit preserved | Same parameterized EQ selector |
| `NONFINITE_VALUES` | Invalid unvalidated/mutated numerical contract (error) | `EQ::test_invalid_constructed_input_blocks_instead_of_claiming_quality` |
| `INVALID_TIMESTAMPS` | Invalid length/count/order/finite time (error) | Same EQ selector; contract rejection also `IN::test_invalid_samples_rejected` |
| `BLANK_VALUES_SKIPPED` | Importer's known omitted blank count (info) | `EQ::test_required_channels_and_skipped_cells_report_known_counts` |
| `INVALID_VALUES_SKIPPED` | Explicit import exclusion count | Same EQ selector |
| `OUT_OF_BOUNDS` | Values outside explicit min/max | `EQ::test_user_stability_and_bounds_use_absolute_stored_si_values`; `EQ::test_details_are_bounded_but_counts_cover_the_whole_capture`; `QA::test_whole_file_quality_is_computed_before_preview_sampling` |
| `STABILITY_EXCEEDED` | Initial median baseline versus absolute declared tolerance | `EQ::test_user_stability_and_bounds_use_absolute_stored_si_values`; `QA::test_custom_quality_expectations_are_read_only_and_reused_in_analysis` |
| `FLATLINE_RUN` | Exactly repeated samples, default run at least 5 | `EQ::test_constant_readings_are_only_potential_stuck_sensor` |
| `ISOLATED_SPIKE` | Sharp isolated excursion versus robust first-difference scale | `EQ::test_spike_and_sustained_step_are_not_conflated`; `EQ::test_boundary_steps_and_isolated_spikes_are_not_double_counted` |
| `BASELINE_CHANGE` | Sustained abrupt neighboring-median change | Same two EQ selectors; smooth-ramp nonflag test: `EQ::test_smooth_ramp_is_not_reported_as_abrupt_steps_or_isolated_spikes` |
| `BOUNDARY_JUMP` | Large adjacent change within two boundary samples, insufficient context | `EQ::test_large_boundary_changes_are_reported_without_claiming_a_cause`; `EQ::test_boundary_steps_and_isolated_spikes_are_not_double_counted` |
| `DUPLICATE_SIGNAL_DATA` | Equal units, values and timestamps across channels | `EQ::test_identical_channels_and_shorter_coverage_are_flagged_separately` |
| `TIMING_UNAVAILABLE` | Row-order/inferred-time axis; elapsed checks skipped (info) | `EQ::test_ordinal_time_skips_elapsed_checks_even_when_expectations_are_supplied` |
| `RECORDING_GAP` | Interval at least 1.5 × explicitly expected cadence; missing physics not proven | `EQ::test_expected_dropout_and_estimated_cadence_have_different_certainty`; `EQ::test_explicit_interval_detects_one_missing_record_without_estimated_gap_factor` |
| `POTENTIAL_RECORDING_GAP` | Interval at least chosen factor × median cadence; default factor 1.8 | `EQ::test_one_missing_position_among_a_thousand_is_still_a_potential_gap`; `EQ::test_expected_dropout_and_estimated_cadence_have_different_certainty` |
| `IRREGULAR_CADENCE` | Over 20% of intervals differ from median by over 10% | `EQ::test_irregular_acquisition_is_identified_without_asserting_missing_samples` |
| `SAMPLE_RATE_MISMATCH` | Median time interval differs from declared-rate interval by over 2% | `EQ::test_declared_rate_mismatch_uses_timestamps_without_changing_them` |
| `CHANNEL_COVERAGE` | Channel window shorter than others by cadence threshold | `EQ::test_identical_channels_and_shorter_coverage_are_flagged_separately` |
| `CATEGORY_CHATTER` | Repeated fast alternating states relative to cadence | `EQ::test_alternating_state_changes_are_possible_chatter_not_diagnosis` |
| `NUMERICAL_RANGE` | Domain overflow/nonfinite output gate | `QA::test_extreme_finite_values_cannot_persist_nonfinite_domain_results` |

Expectation controls: global expected_interval_s/gap_factor/required_channels; per-channel cadence override, expected_stable with mandatory absolute stability_tolerance, min/max, flatline_samples. Unknown keys, nonfinite/bool/text numbers, invalid bounds and duplicate required names fail. `EQ::test_invalid_expectations_are_rejected`, `EQ::test_settings_are_independent_and_channel_interval_overrides_global`, `QA::test_invalid_repairs_or_expectations_do_not_persist`, `QU::test_saved_quality_controls_submit_si_expectations_once_and_download` cover validation and UI/API submission. Zero is a measurement (`EQ::test_zero_values_do_not_mean_missing_values`); extreme finite values retain JSON-safe reports (`EQ::test_large_finite_values_and_intervals_produce_finite_json_reports`).

## Presentation evidence integrity

The offline showcase reads individual scenario/test records instead of trusting a supplied summary. Failed, unknown and missing results remain visible. Its plotted points and units come from saved artifacts; sampled plots use markers rather than inventing continuous detail. The whole-project JUnit total remains distinct from a named L1/L2-related module subset.

Assertions: `SH::test_offline_showcase_uses_real_pass_failure_and_full_suite_counts`, `SH::test_missing_evidence_and_junit_are_unavailable_not_passing`, `SH::test_runner_summary_mismatch_is_flagged_and_unknown_status_is_not_passed`, `SH::test_plots_use_observed_artifact_values_units_and_marker_only_reduction`. Source text cannot inject HTML or escape the evidence directory (`SH::test_evidence_cannot_inject_html_or_escape_source_directory`); the embedded JavaScript is parsed when Node is available (`SH::test_embedded_offline_javascript_parses_when_node_is_available`). These checks verify the presentation generator, not a live browser visual review.

## What this does not demonstrate

There is no live EPICS/archive/cryogenic/LLRF/FRIB logbook connector, machine-control action, image OCR, arbitrary corruption recovery, physical sensor calibration, inferred undeclared physical unit, guaranteed dropout reconstruction or validated fault-cause accuracy. Event attachments can preserve screenshots, but L1/L2 does not interpret their pixels. No anti-alias filtering is added by the alignment helper. X-ray/gradient correlations do not establish field emission, conditioning effectiveness or a safe operating gradient. The cavity-field threshold crossing is an approximate waveform measure, not a fitted physical cavity constant. Missing context outside the recorded window needs an external capture schedule.

Synthetic expected timings/frequencies and controlled analytical waveforms validate implementation behavior. They do not validate performance on operational FRIB faults. L3 retrieval and L4 human review remain available in the wider project; local-model quality and real approved procedures are separate validation tasks.

Quality flags describe recorded patterns and declared-expectation differences. They do not establish why evidence is missing, operator negligence, a future equipment failure or the corrective action that should be taken on a real machine.


## Recorded demonstration crosswalk

The delivered scenario manifest records **49 passed, 0 failed**. This is separate from the full-project JUnit result. Each case includes actual checks, input paths and output paths. This table maps every recorded feature label to its executable case. The complete expected/observed values are in `evidence/cases/<ID>.json` in the presentation kit.

| ID | Scenario | Evidence scope | Recorded features |
|---|---|---|---|
| `L1-01` | Mixed CSV preview and canonical import | API TestClient | `mixed_csv`, `column_roles`, `booleans`, `severity_labels`, `preview_no_write`, `canonical_import` |
| `L1-02` | Per-row units and explicit target mapping | API TestClient | `per_row_units`, `header_units`, `quantity_suffix`, `target_units` |
| `L1-03` | TXT, Markdown, LOG and text PDF | API TestClient | `txt`, `markdown`, `log`, `text_pdf`, `narrative_states`, `relative_time` |
| `L1-04` | ISO datetime and explicit ordinal timelines | deterministic helper | `iso_datetime`, `datetime_anchor`, `ordinal_time`, `time_units` |
| `L1-05` | Strict JSON schema and raw versus normalized exports | API TestClient | `json_schema`, `boolean_rejection`, `timestamp_contract`, `raw_export`, `normalized_export`, `provenance` |
| `L1-06` | Structural and encoding detector inventory | deterministic helper | `invalid_upload`, `unreadable_text`, `empty_file`, `empty_header`, `duplicate_headers`, `csv_syntax`, `no_data_rows`, `column_limit`, `unreadable_document` |
| `L1-07` | Combined malformed-row and missing-data findings | API TestClient and deterministic helper | `row_shape`, `missing_tokens`, `mixed_numeric_text`, `duplicate_rows`, `time_reversal`, `duplicate_timestamps`, `missing_cells`, `possible_truncation` |
| `L1-08` | Time declaration, invalid time and legitimate ties | deterministic helper | `unsupported_time_unit`, `time_unit_unconfirmed`, `invalid_timestamp`, `inferred_time`, `disjoint_timestamp_ties` |
| `L1-09` | Numeric, sentinel and unit conflict detectors | deterministic helper | `unsupported_unit`, `nonfinite_values`, `invalid_numeric`, `possible_sentinel`, `incompatible_units`, `missing_unit`, `mixed_unit_scales`, `insufficient_numeric_samples` |
| `L1-10` | Unit suggestions require confirmation | API TestClient and deterministic helper | `high_confidence_units`, `medium_suffix_suggestion`, `low_name_suggestion`, `temperature_ambiguity`, `no_unit_inference` |
| `L1-11` | Explicit row repairs, sorting and missing tokens | deterministic helper | `drop_malformed_rows`, `drop_exact_duplicate_rows`, `mark_missing_tokens`, `sort_by_time`, `repair_receipt`, `physical_source_rows` |
| `L1-12` | Selected cell repairs preserve originals and notes | API TestClient | `drop_invalid_numeric_cells`, `repair_original_preservation`, `derived_attachment`, `repair_restart`, `source_vs_copy_rows` |
| `L1-13` | Repair whitelist rejects guesses and ambiguous edits | deterministic helper | `repair_whitelist`, `no_fill`, `no_interpolation`, `no_unit_deletion`, `timestamp_repair_rejection`, `numeric_only_repairs` |
| `L1-14` | Bounded inspection and upload limits | API TestClient and patched helper bounds (small fixtures) | `inspection_limit`, `byte_limit`, `row_limit`, `column_limit`, `bounded_examples`, `accurate_counts` |
| `L1-15` | Skip policy and invalid mapping validation | API TestClient and deterministic helper | `explicit_skip_policy`, `invalid_options`, `skip_unit_anchor`, `atomic_invalid_import` |
| `L1-16` | Preview sampling validates the complete capture | API TestClient | `preview_sampling`, `full_file_validation`, `full_import_retention` |
| `L1-17` | Evidence file lifecycle and duplicate protection | API TestClient | `file_add_download_delete`, `exact_original_bytes`, `duplicate_409`, `restart_persistence` |
| `L1-18` | Narrative review and cascade deletion after restart | API TestClient | `narrative_analysis`, `human_review`, `cascade_delete`, `audit`, `restart_delete` |
| `UNITS-01` | Every registered unit round-trips through canonical SI | API TestClient and deterministic helper | `unit_catalog`, `all_unit_families`, `case_sensitive_prefix`, `temperature_offset`, `temperature_difference`, `quantity_parser` |
| `UNITS-02` | Unknown, incompatible and nonfinite conversions rejected | API TestClient and deterministic helper | `incompatible_dimensions`, `unknown_units`, `boolean_rejection`, `nonfinite_rejection`, `conversion_overflow` |
| `UNITS-03` | Normalization copies evidence and retains legacy warnings | deterministic helper | `normalization_nonmutation`, `conversion_provenance`, `normalization_idempotency`, `legacy_unknown_preserved`, `legacy_missing_preserved` |
| `L2-01` | Good captures and real zero readings | deterministic helper | `good_capture`, `zero_not_missing`, `pure_assessment` |
| `L2-02` | Potential flatline runs | deterministic helper | `FLATLINE_RUN`, `flatline_samples`, `conservative_warning` |
| `L2-03` | Robust isolated spike and sustained step | deterministic helper | `ISOLATED_SPIKE`, `BASELINE_CHANGE`, `change_separation` |
| `L2-04` | Boundary changes and smooth-trend negative control | deterministic helper | `BOUNDARY_JUMP`, `boundary_context`, `smooth_trend_control` |
| `L2-05` | Configured recording gap with bounded intervals | deterministic helper | `RECORDING_GAP`, `expected_interval_s`, `gap_intervals`, `estimated_missing_count` |
| `L2-06` | Estimated cadence detects one missing position | deterministic helper | `POTENTIAL_RECORDING_GAP`, `robust_cadence`, `single_missing_position` |
| `L2-07` | Irregular acquisition and sample-rate mismatch | deterministic helper | `IRREGULAR_CADENCE`, `SAMPLE_RATE_MISMATCH`, `timestamp_authority` |
| `L2-08` | Operator stability tolerance and SI bounds | API TestClient and deterministic helper | `STABILITY_EXCEEDED`, `OUT_OF_BOUNDS`, `absolute_si_tolerance`, `bounded_issue_locations` |
| `L2-09` | Missing and unknown legacy signal units | deterministic helper | `UNSPECIFIED_UNIT`, `UNKNOWN_UNIT`, `no_name_based_units` |
| `L2-10` | Duplicate channel data and unequal coverage | deterministic helper | `DUPLICATE_SIGNAL_DATA`, `CHANNEL_COVERAGE` |
| `L2-11` | Required channels and unmatched expectation names | deterministic helper | `MISSING_CHANNEL`, `UNMATCHED_EXPECTATION`, `self_contained_expectations` |
| `L2-12` | Known skipped-cell counts remain visible | deterministic helper | `BLANK_VALUES_SKIPPED`, `INVALID_VALUES_SKIPPED`, `no_missing_fill` |
| `L2-13` | Potential categorical chatter | deterministic helper | `CATEGORY_CHATTER`, `categorical_timing` |
| `L2-14` | Narrative-only and ordinal timing limits | deterministic helper | `NO_NUMERIC_SIGNALS`, `TIMING_UNAVAILABLE`, `ordinal_skips_elapsed_checks` |
| `L2-15` | Defensive checks for invalid adapter contracts | unvalidated adapter helper (not public ingestion) | `NONFINITE_VALUES`, `INVALID_TIMESTAMPS`, `defensive_contract_check` |
| `L2-16` | Extreme finite arithmetic and JSON safety | deterministic helper | `finite_json`, `overflow_intervals`, `accurate_bounded_counts` |
| `L2-17` | Strict quality settings and per-channel cadence override | deterministic helper | `settings_validation`, `channel_cadence_override`, `strict_finite_config` |
| `ANALYSIS-01` | RF trip, decay and forward/reflected comparison | API TestClient and deterministic domain helper | `rf_trip`, `cavity_decay`, `pressure_pre_post`, `forward_reflected_ratio`, `rf_plots` |
| `ANALYSIS-02` | X-ray and gradient trends remain descriptive | API TestClient | `field_emission_trends`, `xray_gradient_correlation`, `scatter_plot`, `conditioning_limitations` |
| `ANALYSIS-03` | Mechanical RMS and calibrated FFT | API TestClient and deterministic helper | `mechanical_rms`, `fft_frequency`, `fft_amplitude`, `native_timestamp_rate`, `fft_plot` |
| `ANALYSIS-04` | PLC chronology, repeated transitions and incomplete sequences | API TestClient and deterministic helper | `plc_chronology`, `transition_intervals`, `sequence_validation`, `categorical_timeline` |
| `ANALYSIS-05` | Common-grid alignment and no-extrapolation provenance | deterministic helper | `grid_alignment`, `overlap_only`, `no_extrapolation`, `raw_unchanged`, `downsample_warning`, `alignment_bound` |
| `ANALYSIS-06` | Adapter cleaning records transformations without raw edits | unvalidated adapter helper (not public ingestion) | `adapter_cleaning`, `nonfinite_removed`, `duplicate_times_averaged`, `stable_sort`, `cleaning_provenance` |
| `ANALYSIS-07` | Gaps, irregular timing and ordinal order withhold spectra | API TestClient | `gap_analysis_gate`, `irregular_analysis_gate`, `ordinal_analysis_gate`, `no_gap_interpolation`, `sample_rate_mismatch_allowed` |
| `ANALYSIS-08` | Extreme domain values fall back to finite descriptive evidence | API TestClient | `NUMERICAL_RANGE`, `finite_domain_results`, `overflow_fallback`, `evidence_retained` |
| `GEN-01` | Three reproducible generators and operational metadata | API TestClient and generator helper | `three_generators`, `deterministic_seed`, `custom_overrides`, `operational_metadata`, `dataset_name` |
| `GEN-02` | Generator bounds and scenario-time validation | deterministic generator helper | `generator_bounds`, `finite_parameters`, `sample_count_bounds`, `nyquist_bound`, `ordered_scenario_times` |
| `FORMAT-01` | BOM, delimiters, quoted cells and ignored columns | deterministic ingestion helper | `utf8_bom`, `semicolon_csv`, `tab_csv`, `pipe_csv`, `quoted_fields`, `ignore_role` |
