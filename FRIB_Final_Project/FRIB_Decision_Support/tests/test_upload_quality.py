from copy import deepcopy
import csv
import hashlib
import io

import pytest

from frib_ds.ingestion import build_event
from frib_ds.ingestion.quality import assess_upload, repair_upload


def issue(report, code, column=None):
    return next(item for item in report["issues"] if item["code"] == code and (column is None or item["column"] == column))


def codes(report):
    return {item["code"] for item in report["issues"]}


def parsed(contents):
    return list(csv.reader(io.StringIO(contents.decode("utf-8-sig"), newline="")))


def test_raw_csv_collects_shape_numeric_missing_duplicate_and_time_problems():
    contents = b"time [s],pressure [kPa],mode\n0,1,OFF\n2,NAN,ON\n1,operator note,ON\n1,operator note,ON\n3,,OFF\n4,9"
    options = {"column_roles": {"pressure [kPa]": "numeric", "mode": "category"}}
    report = assess_upload("bad.csv", contents, options)
    assert report["version"] == "1.0" and report["stage"] == "L1" and report["status"] == "blocked"
    assert {"row_shape", "missing_tokens", "mixed_numeric_text", "duplicate_rows", "time_reversal", "duplicate_timestamps", "missing_cells", "possible_truncation"} <= codes(report)
    assert issue(report, "row_shape")["rows"] == [7]
    assert issue(report, "mixed_numeric_text")["rows"] == [4, 5]
    assert issue(report, "duplicate_rows")["count"] == 1
    assert issue(report, "missing_tokens")["repair"] == {"operation": "mark_missing_tokens", "columns": ["pressure [kPa]"]}
    assert all(set(item) == {"code", "severity", "title", "message", "column", "rows", "timestamps_s", "count", "suggestion", "repair"} for item in report["issues"])
    assert report["summary"]["error"] == sum(item["severity"] == "error" for item in report["issues"])


@pytest.mark.parametrize("contents,code", [
    (b"x,x\n1,2\n", "duplicate_headers"), (b"x,\n1,2\n", "empty_header"),
    (b"x [V]\n\"unfinished", "csv_syntax"), (b'"broken\n', "csv_syntax"),
    (b"x [V]\n", "no_data_rows"), (b"\xff", "unreadable_text"),
    (b"\x00", "unreadable_text"), (b"", "invalid_upload"),
])
def test_unreadable_or_incomplete_csv_returns_flags_not_exceptions(contents, code):
    report = assess_upload("source.csv", contents)
    assert report["status"] == "blocked" and code in codes(report)


def test_bad_quotes_remain_blocked_even_with_skip_invalid_selected():
    contents = b'time,x [V]\n0,1\n1,"unfinished\n'
    report = assess_upload("quotes.csv", contents, {"invalid_rows": "skip"})
    assert issue(report, "csv_syntax")["severity"] == "error"
    with pytest.raises(ValueError, match="prevent safe repair"):
        repair_upload("quotes.csv", contents, {}, [{"operation": "drop_malformed_rows", "rows": [3]}])


def test_skip_policy_warns_about_skippable_cells_and_time_but_blocks_insufficient_capture():
    contents = b"time [s],x [V]\n0,1\n1,NAN\nno time,5\n2,3\n"
    report = assess_upload("skip.csv", contents, {"invalid_rows": "skip"})
    assert report["status"] == "review"
    assert issue(report, "missing_tokens")["severity"] == "warning"
    assert issue(report, "invalid_timestamp")["severity"] == "warning"
    assert len(build_event("skip.csv", contents, {"invalid_rows": "skip"}).signals[0].values) == 2
    short = assess_upload("short.csv", b"time [s],x [V]\n0,1\nno time,2\n", {"invalid_rows": "skip"})
    assert issue(short, "insufficient_numeric_samples")["severity"] == "error"


def test_skipped_invalid_time_cannot_define_units_for_accepted_numeric_rows():
    contents = b"time [s],reading\ninvalid,1 Pa\n0,1 V\n1,2 V\n"
    report = assess_upload("skipunits.csv", contents, {"invalid_rows": "skip"})
    assert report["status"] == "review"
    assert "insufficient_numeric_samples" not in codes(report)
    assert build_event("skipunits.csv", contents, {"invalid_rows": "skip"}).signals[0].unit == "V"


def test_duplicate_timestamp_only_blocks_numeric_channels_with_duplicate_samples():
    contents = b"time [s],a [V],b [V]\n0,1,\n0,,2\n1,3,4\n"
    report = assess_upload("separate.csv", contents)
    assert issue(report, "duplicate_timestamps")["severity"] == "warning"
    assert report["status"] == "review"
    assert len(build_event("separate.csv", contents).signals) == 2
    conflict = assess_upload("repeat.csv", b"time [s],a [V]\n0,1\n0,2\n1,3\n")
    assert issue(conflict, "duplicate_timestamps")["severity"] == "error"


def test_mixed_numeric_text_unmapped_is_reviewed_without_reclassifying_prose():
    contents = b"time [s],observation\n0,1\n1,operator stopped acquisition\n2,2\n"
    report = assess_upload("mixed.csv", contents)
    assert report["status"] == "review"
    assert issue(report, "mixed_numeric_text")["severity"] == "warning"
    assert issue(report, "mixed_numeric_text")["repair"] is None
    explicit_text = assess_upload("mixed.csv", contents, {"column_roles": {"observation": "log"}})
    assert "mixed_numeric_text" not in codes(explicit_text)


def test_all_placeholder_column_is_reviewed_without_assuming_a_numeric_role():
    contents = b"time [s],pressure\n0,NA\n1,NAN\n"
    report = assess_upload("placeholders.csv", contents)
    assert issue(report, "missing_tokens")["severity"] == "warning"
    assert issue(report, "missing_tokens")["repair"] is None
    assert report["status"] == "review"
    categorical = assess_upload("placeholders.csv", contents, {"column_roles": {"pressure": "category"}})
    assert "missing_tokens" not in codes(categorical)


def test_unlabelled_time_unit_is_flagged_and_can_be_explicitly_confirmed():
    contents = b"time,x [V]\n0,1\n1,2\n"
    assert "time_unit_unconfirmed" in codes(assess_upload("time.csv", contents))
    assert "time_unit_unconfirmed" not in codes(assess_upload("time.csv", contents, {"time_unit": "ms"}))


def test_sentinels_are_flagged_without_deleting_or_reinterpreting_real_numbers():
    contents = b"time [s],x [V]\n0,-9999\n1,2\n2,Infinity\n"
    report = assess_upload("sentinel.csv", contents)
    assert issue(report, "possible_sentinel")["severity"] == "warning"
    assert issue(report, "nonfinite_values")["rows"] == [4]
    result, receipt = repair_upload("sentinel.csv", contents, {}, [{"operation": "drop_invalid_numeric_cells", "columns": ["x [V]"], "rows": [2, 4]}])
    assert parsed(result)[1][1] == "-9999" and parsed(result)[3][1] == ""
    assert receipt["changes"][0]["count"] == 1


def test_unit_declarations_conflicts_and_mixed_prefixes_are_visible():
    contents = b"time [s],voltage [V]\n0,1 V\n1,2 kV\n2,3 Pa\n3,4 V\n"
    report = assess_upload("units.csv", contents)
    assert issue(report, "mixed_unit_scales")["severity"] == "warning"
    assert issue(report, "incompatible_units")["rows"] == [4]
    suggestions = report["unit_suggestions"][0]
    assert suggestions["column"] == "voltage [V]" and suggestions["assigned"] is False
    assert {candidate["unit"] for candidate in suggestions["candidates"]} == {"V", "kV"}
    unknown = assess_upload("unknown.csv", b"time [s],power [dBm]\n0,1\n1,2\n")
    assert issue(unknown, "unsupported_unit")["severity"] == "error"
    mapped = assess_upload("unknown.csv", b"time [s],power [dBm]\n0,1\n1,2\n", {"source_units": {"power [dBm]": "W"}})
    assert "unsupported_unit" not in codes(mapped)


def test_per_row_units_detected_without_missing_unit_guess():
    contents = b"time [s],pressure,pressure_unit\n0,100,kPa\n1,1,bar\n2,200,kPa\n"
    report = assess_upload("rowunits.csv", contents)
    assert "missing_unit" not in codes(report)
    assert issue(report, "mixed_unit_scales")["column"] == "pressure"
    assert {candidate["unit"] for candidate in report["unit_suggestions"][0]["candidates"]} == {"kPa", "bar"}


def test_unit_column_dimension_conflict_is_not_hidden_by_cell_suffix():
    contents = b"time [s],x,unit\n0,1 V,V\n1,2 V,Pa\n2,3 V,V\n"
    report = assess_upload("conflict.csv", contents, {"unit_columns": {"x": "unit"}})
    assert issue(report, "incompatible_units")["rows"] == [3]


def test_temperature_names_produce_ambiguous_candidates_without_offset_guessing():
    contents = b"time [s],temperature\n0,20\n1,21\n"
    options = {}
    original = deepcopy(options)
    report = assess_upload("temp.csv", contents, options)
    assert options == original
    proposal = report["unit_suggestions"][0]
    assert {candidate["unit"] for candidate in proposal["candidates"]} == {"C", "K", "F"}
    assert all(candidate["confidence"] == "low" for candidate in proposal["candidates"])
    assert proposal["requires_confirmation"] is True and proposal["assigned"] is False
    assert build_event("temp.csv", contents).signals[0].unit == "1"
    delta = assess_upload("delta.csv", contents.replace(b"temperature", b"temperature_difference"))
    assert {candidate["unit"] for candidate in delta["unit_suggestions"][0]["candidates"]} == {"delta_C", "delta_K", "delta_F"}


def test_name_suffix_and_ambiguous_names_remain_unassigned_candidates():
    report = assess_upload("suffix.csv", b"time [s],voltage_mV\n0,1\n1,2\n")
    candidate = next(candidate for candidate in report["unit_suggestions"][0]["candidates"] if candidate["unit"] == "mV")
    assert candidate["confidence"] == "medium"
    report = assess_upload("ambiguous.csv", b"time [s],pressure_temperature\n0,1\n1,2\n")
    units = {candidate["unit"] for candidate in report["unit_suggestions"][0]["candidates"]}
    assert {"Pa", "kPa", "C", "K", "F"} <= units
    assert "missing_unit" in codes(report)


def test_explicit_measurement_repairs_preserve_text_originals_and_checksums():
    contents = b'time [s],x [V],mode,note\n2,2,NA,"retain, quoted text"\n0,NA,ON,"line one\nline two"\n0,NA,ON,"line one\nline two"\n1,1,OFF,done\n3,9\n'
    options = {"column_roles": {"x [V]": "numeric", "mode": "category", "note": "log"}}
    repairs = [{"operation": "drop_malformed_rows", "rows": [8]}, {"operation": "drop_exact_duplicate_rows"},
        {"operation": "mark_missing_tokens", "columns": ["x [V]"]}, {"operation": "sort_by_time"}]
    result, receipt = repair_upload("repair.csv", contents, options, repairs)
    assert contents.endswith(b"3,9\n")
    rows = parsed(result)
    assert [row[0] for row in rows[1:]] == ["0", "1", "2"]
    assert rows[1][1] == "" and rows[1][3] == "line one\nline two"
    assert rows[3][2:] == ["NA", "retain, quoted text"]
    assert [change["count"] for change in receipt["changes"]] == [1, 1, 1, 3]
    assert receipt["before_checksum"] == hashlib.sha256(contents).hexdigest()
    assert receipt["after_checksum"] == hashlib.sha256(result).hexdigest()
    assert receipt["input_rows"] == 5 and receipt["output_rows"] == 3
    assert assess_upload("repair.csv", result, options)["status"] == "review"  # Missing data remains visible.
    assert len(build_event("repair.csv", result, options).signals[0].values) == 2


def test_repairs_are_idempotent_and_keep_blank_records_and_text():
    contents = b"time [s];x [V];note\r\n0;NA;NA is prose\r\n\r\n1;2;done\r\n1;2;done\r\n2;3;end\r\n"
    repairs = [{"action": "mark_missing_tokens", "columns": ["x [V]"]}, {"operation": "drop_exact_duplicate_rows"}]
    first, receipt = repair_upload("idempotent.csv", contents, {}, repairs)
    assert b"\r\n\r\n" in first and b"NA is prose" in first
    second, repeated = repair_upload("idempotent.csv", first, {}, repairs)
    assert second == first
    assert all(change["count"] == 0 for change in repeated["changes"])
    assert repeated["before_checksum"] == repeated["after_checksum"]
    assert receipt["changes"][0]["operation"] == "mark_missing_tokens"


def test_cell_selection_uses_original_physical_rows_after_sorting():
    contents = b"time [s],x [V],note\n2,2,retain\n0,NAN,missing\n1,1,retain\n"
    result, receipt = repair_upload("locations.csv", contents, {}, [
        {"operation": "sort_by_time"}, {"operation": "mark_missing_tokens", "columns": ["x [V]"], "rows": [3]}])
    assert parsed(result)[1] == ["0", "", "missing"]
    assert receipt["changes"][1]["locations"] == [{"row": 3, "end_row": 3, "column": "x [V]"}]


@pytest.mark.parametrize("repair,match", [
    ({"operation": "interpolate"}, "Unsupported"), ({"operation": "fill", "value": 0}, "Unsupported"),
    ({"operation": "drop_malformed_rows"}, "selected rows"),
    ({"operation": "drop_invalid_numeric_cells", "columns": ["x [V]"]}, "selected rows"),
    ({"operation": "mark_missing_tokens", "columns": ["note"]}, "numeric measurement"),
    ({"operation": "mark_missing_tokens", "columns": ["x [V]"], "tokens": ["operator"]}, "recognized"),
    ({"operation": "drop_malformed_rows", "rows": [2]}, "incorrect field counts"),
    ({"operation": "drop_exact_duplicate_rows", "rows": [2]}, "nonduplicate"),
    ({"operation": "sort_by_time", "rows": [2]}, "subsets"),
    ({"operation": "mark_missing_tokens", "columns": ["missing"]}, "do not exist"),
    ({"operation": "sort_by_time", "action": "mark_missing_tokens"}, "Conflicting"),
])
def test_unsupported_ambiguous_or_unselected_repairs_are_rejected(repair, match):
    contents = b"time [s],x [V],note\n0,1,NA\n1,2,operator\n"
    with pytest.raises(ValueError, match=match):
        repair_upload("safe.csv", contents, {}, [repair])


def test_unit_errors_and_unreadable_timestamps_cannot_be_repaired_by_deletion_or_guessing():
    contents = b"time [s],x [V]\n0,1\n1,2 Pa\n2,3\n"
    with pytest.raises(ValueError, match="Unit errors"):
        repair_upload("units.csv", contents, {}, [{"operation": "drop_invalid_numeric_cells", "columns": ["x [V]"], "rows": [3]}])
    with pytest.raises(ValueError, match="Every timestamp"):
        repair_upload("time.csv", b"time [s],x [V]\n0,1\nunknown,2\n", {}, [{"operation": "sort_by_time"}])
    with pytest.raises(ValueError, match="measured timestamp"):
        repair_upload("order.csv", b"x [V]\n2\n1\n", {}, [{"operation": "sort_by_time"}])


def test_bounded_details_retain_exact_issue_and_repair_counts():
    contents = b"time [s],x [V]\n" + b"0,1\n" * 41 + b"1,2\n"
    report = assess_upload("duplicates.csv", contents)
    duplicate = issue(report, "duplicate_rows")
    assert duplicate["count"] == 40 and len(duplicate["rows"]) == 25
    result, receipt = repair_upload("duplicates.csv", contents, {}, [{"operation": "drop_exact_duplicate_rows"}])
    change = receipt["changes"][0]
    assert change["count"] == 40 and len(change["locations"]) == 25 and change["locations_truncated"]
    assert len(parsed(result)) == 3


@pytest.mark.parametrize("options", [{"time_unit": []}, {"time_column": []}, {"source_units": {"x [V]": []}}, {"column_roles": {"x [V]": {}}}, {"metadata": "bad"}])
def test_malformed_mapping_options_are_reported(options):
    report = assess_upload("options.csv", b"time [s],x [V]\n0,1\n1,2\n", options)
    assert issue(report, "invalid_options")["severity"] == "error"


def test_upload_and_cell_bounds_stop_assessment_and_repair(monkeypatch):
    from frib_ds.ingestion import common, quality
    monkeypatch.setattr(common, "MAX_BYTES", 10)
    assert assess_upload("limit.csv", b"time,x\n0,1\n1,2\n")["status"] == "blocked"
    monkeypatch.setattr(common, "MAX_BYTES", 1024)
    monkeypatch.setattr(quality, "MAX_CELLS", 3)
    contents = b"time [s],x [V]\n0,1\n1,2\n"
    report = assess_upload("limit.csv", contents)
    assert "inspection_limit" in codes(report)
    with pytest.raises(ValueError, match="prevent safe repair"):
        repair_upload("limit.csv", contents, {}, [{"operation": "drop_exact_duplicate_rows"}])


def test_narrative_assessment_exposes_timing_limits_and_refuses_csv_repairs():
    report = assess_upload("notes.txt", b"Operator reviewed the sensor.\n")
    assert report["status"] == "review" and "document_limitation" in codes(report)
    with pytest.raises(ValueError, match="CSV and TSV only"):
        repair_upload("notes.txt", b"Operator reviewed the sensor.\n", {}, [{"operation": "sort_by_time"}])
