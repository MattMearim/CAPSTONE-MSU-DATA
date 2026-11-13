from copy import deepcopy
import hashlib
import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from frib_ds.ingestion import build_event, inspect_upload


def by_name(event):
    return {signal.name: signal for signal in event.signals}


def test_mixed_csv_preserves_measurements_categories_logs_and_provenance():
    contents = b"time [ms],pressure [kPa],mode,permit,message\n0,100,OFF,false,[INFO] capture started\n10,1.2 bar,ON,true,[WARN] valve changed\n20,130,ON,true,[ERROR] check sensor\n"
    options = {"event_id": "MIX-1", "domain": "rf", "dataset_name": "Capture", "metadata": {"operator": "test"},
        "column_roles": {"pressure [kPa]": "numeric", "mode": "category", "permit": "category", "message": "log"}}
    before = deepcopy(options)
    preview = inspect_upload("mixed.csv", contents)
    event = build_event("mixed.csv", contents, options)
    assert options == before
    assert preview["suggested_time_unit"] == "ms"
    assert preview["row_count"] == 3
    assert by_name(event)["pressure"].timestamps_s == pytest.approx([0, .01, .02])
    assert by_name(event)["pressure"].values == pytest.approx([100, 120, 130])
    assert by_name(event)["pressure"].unit == "kPa"
    assert [(state.name, state.value) for state in event.states] == [("mode", "OFF"), ("permit", "false"), ("mode", "ON"), ("permit", "true")]
    assert [log.level for log in event.logs] == ["INFO", "WARNING", "ERROR"]
    summary = event.metadata["import_summary"]
    assert summary["category_frequencies"]["mode"] == {"OFF": 1, "ON": 2}
    assert summary["log_severity_distribution"] == {"INFO": 1, "WARNING": 1, "ERROR": 1}
    assert summary["unit_conversions"] == [{"column": "pressure [kPa]", "source_unit": "bar", "target_unit": "kPa", "count": 1}]
    assert summary["numeric_signals"] == 1 and summary["state_changes"] == 4 and summary["log_entries"] == 3
    assert event.provenance.checksum == hashlib.sha256(contents).hexdigest()
    assert event.metadata["operator"] == "test" and event.event_type == "evidence_record"
    assert event.attachments == []  # Callers persist the exact original upload.


def test_csv_units_column_and_explicit_quantity_scales():
    contents = b"time [s],voltage,voltage_unit\n0,1000,mV\n1,2 kV,V\n2,500,mV\n"
    preview = inspect_upload("units.csv", contents)
    voltage_profile = next(column for column in preview["columns"] if column["name"] == "voltage")
    assert voltage_profile["suggested_unit_column"] == "voltage_unit"
    options = {"unit_columns": {"voltage": "voltage_unit"}, "target_units": {"voltage": "V"}}
    original = deepcopy(options)
    event = build_event("units.csv", contents, options)
    assert options == original
    assert by_name(event)["voltage"].values == pytest.approx([1, 2000, .5])
    assert event.states == []
    assert event.metadata["import_summary"]["column_roles"]["voltage_unit"] == "ignore"


def test_cell_unit_cannot_contradict_unit_column_dimension():
    with pytest.raises(ValueError, match="row 3.*voltage.*Incompatible units"):
        build_event("conflict.csv", b"time,voltage,unit\n0,1 V,V\n1,2 V,Pa\n", {"unit_columns": {"voltage": "unit"}})


def test_blank_samples_keep_each_channels_actual_timestamps():
    event = build_event("blank.csv", b"time [ms],a [V],b [V]\n0,1,\n10,,4\n30,3,5\n")
    channels = by_name(event)
    assert channels["a"].timestamps_s == pytest.approx([0, .03])
    assert channels["b"].timestamps_s == pytest.approx([.01, .03])
    assert channels["a"].sample_rate_hz == pytest.approx(1 / .03)
    assert event.metadata["import_summary"]["blank_numeric_cells_skipped"] == {"a [V]": 1, "b [V]": 1}


def test_explicit_numeric_role_rejects_arbitrary_text_and_skip_is_counted():
    contents = b"time,x\n0,1\n1,operator says ready\n2,3\n"
    with pytest.raises(ValueError, match="row 3.*numeric column 'x'"):
        build_event("bad.csv", contents, {"column_roles": {"x": "numeric"}})
    event = build_event("bad.csv", contents, {"column_roles": {"x": "numeric"}, "invalid_rows": "skip"})
    assert event.signals[0].values == [1, 3]
    assert event.signals[0].timestamps_s == [0, 2]
    assert event.metadata["import_summary"]["invalid_numeric_cells_skipped"] == {"x": 1}


def test_missing_units_are_dimensionless_without_physical_inference():
    event = build_event("pressure.csv", b"pressure\n1\n2\n")
    assert event.signals[0].unit == "1"
    assert event.metadata["import_summary"]["time_basis"] == "row_index"
    assert event.signals[0].metadata["inferred_time"] is True
    assert any("no physical unit" in note for note in event.metadata["import_summary"]["warnings"])
    assert event.domain == "other"


def test_bare_numeric_preview_leaves_unit_blank_and_empty_ui_source_preserves_warning():
    contents = b"time [s],voltage\n0,1\n1,2\n"
    preview = inspect_upload("bare.csv", contents)
    profile = next(column for column in preview["columns"] if column["name"] == "voltage")
    assert profile["suggested_unit"] == ""
    assert any("confirm its source unit" in warning for warning in preview["warnings"])
    event = build_event("bare.csv", contents, {"source_units": {"voltage": ""}})
    assert event.signals[0].unit == "1"
    assert any("no physical unit" in note for note in event.metadata["import_summary"]["notes"])


def test_unsupported_declared_unit_is_preserved_in_preview_and_requires_override():
    contents = b"time [s],power [dBm]\n0,1\n1,2\n"
    preview = inspect_upload("unsupported.csv", contents)
    profile = next(column for column in preview["columns"] if column["name"] == "power [dBm]")
    assert profile["suggested_unit"] == "dBm"
    assert any("unsupported unit 'dBm'" in warning for warning in preview["warnings"])
    with pytest.raises(ValueError, match="Unknown unit.*dBm"):
        build_event("unsupported.csv", contents)
    event = build_event("unsupported.csv", contents, {"source_units": {"power [dBm]": "W"}})
    assert event.signals[0].unit == "W"  # An explicit user correction is required.


def test_time_header_cannot_silently_discard_non_time_unit():
    contents = b"time [V],reading [V]\n0,1\n1,2\n"
    with pytest.raises(ValueError, match="explicitly choose.*time_unit"):
        build_event("badtime.csv", contents)
    event = build_event("badtime.csv", contents, {"time_unit": "ms"})
    assert event.signals[0].timestamps_s == pytest.approx([0, .001])


@pytest.mark.parametrize("suffix,scale", [("ms", .001), ("us", .000001), ("ns", 1e-9)])
def test_time_header_suffix_infers_real_scale(suffix, scale):
    contents = f"time_{suffix},reading [V]\n0,1\n100,2\n".encode()
    assert inspect_upload("suffix.csv", contents)["suggested_time_unit"] == suffix
    assert build_event("suffix.csv", contents).signals[0].timestamps_s == pytest.approx([0, 100 * scale])


def test_datetime_csv_sorted_without_losing_original_row_provenance():
    contents = b"timestamp,mode,value [V]\n2026-10-10T12:00:02Z,ON,2\n2026-10-10T12:00:00Z,OFF,1\n"
    event = build_event("date.csv", contents)
    assert event.signals[0].values == [1, 2]
    assert [state.value for state in event.states] == ["OFF", "ON"]
    assert event.states[0].metadata["source_row"] == 3
    assert event.signals[0].timestamps_s == [-2, 0]
    assert any("ordered" in note for note in event.metadata["import_summary"]["notes"])


def test_delimiter_bom_and_explicit_source_target_units():
    contents = "\ufefftime;voltage;comment\n0;1000;capture started\n1;2000;capture ended\n".encode("utf-8")
    event = build_event("semicolon.csv", contents, {"source_units": {"voltage": "mV"}, "target_units": {"voltage": "V"}})
    assert event.signals[0].values == [1, 2]
    assert event.metadata["import_summary"]["delimiter"] == ";"
    assert len(event.logs) == 2


@pytest.mark.parametrize("contents,options,match", [
    (b"time,x [V]\n0,1\n0,2\n", {}, "distinct increasing"),
    (b"time,x [V]\n0,1\n1,2 Pa\n", {}, "Incompatible units"),
    (b"time,x\n0,NaN\n1,2\n", {"column_roles": {"x": "numeric"}}, "row 2"),
    (b"time,x\n0,1\n1,\n", {}, "fewer than two"),
    (b"time,x\n0,1\n1,2\n", {"column_roles": {"x": "ignore"}}, "No evidence"),
    (b"x,x\n1,2\n", {}, "unique"),
    (b"time,x\n0,1,2\n", {}, "fields"),
])
def test_invalid_csv_is_actionable(contents, options, match):
    with pytest.raises(ValueError, match=match):
        build_event("bad.csv", contents, options)


@pytest.mark.parametrize("options", [
    {"column_roles": {"x": []}}, {"time_unit": []}, {"time_column": []},
    {"source_units": {"x": {}}}, {"target_units": {"x": None}},
    {"unit_columns": {"x": []}}, {"signal_names": {"x": 2}}, {"metadata": "text"},
])
def test_structured_invalid_options_raise_value_error(options):
    with pytest.raises(ValueError):
        build_event("options.csv", b"time,x\n0,1\n1,2\n", options)


def test_narrative_relative_time_explicit_states_and_severity():
    contents = b"0 ms [INFO] mode=OFF\n\n20 ms [WARN] mode=ON pressure=1.2\n40 ms [ERROR] mode=ON review requested\n"
    preview = inspect_upload("shift.log", contents)
    assert preview["format"] == "text" and preview["row_count"] == 3
    assert "mode=OFF" in preview["text_preview"]
    assert preview["suggested_time_unit"] == "s"
    event = build_event("shift.log", contents)
    assert [log.timestamp_s for log in event.logs] == pytest.approx([0, .02, .04])
    assert [log.level for log in event.logs] == ["INFO", "WARNING", "ERROR"]
    assert [log.message for log in event.logs] == [line for line in contents.decode().splitlines() if line.strip()]
    assert [(state.name, state.value) for state in event.states] == [("mode", "OFF"), ("mode", "ON")]
    assert event.signals == []
    assert event.logs[1].metadata["source_line"] == 3
    assert event.logs[1].metadata["original_timestamp"] == "20 ms"
    assert event.metadata["import_summary"]["category_frequencies"] == {"mode": {"OFF": 1, "ON": 2}}


def test_datetime_narrative_anchors_real_timing_and_orders_states():
    contents = b"2026-10-10T12:00:02Z [ERROR] permit=false\n2026-10-10T12:00:00Z [INFO] permit=true\n"
    event = build_event("shift.txt", contents)
    assert event.timestamp.isoformat() == "2026-10-10T12:00:00+00:00"
    assert [log.timestamp_s for log in event.logs] == [0, 2]
    assert [log.level for log in event.logs] == ["INFO", "ERROR"]
    assert [state.value for state in event.states] == ["true", "false"]
    assert event.metadata["import_summary"]["time_basis"] == "datetime"


def test_narrative_missing_or_mixed_timestamps_uses_honest_row_coordinates():
    contents = b"5 s [INFO] ready\noperator says pressure spike\n2026-10-10T12:00:10Z [WARNING] inspect evidence\n"
    event = build_event("notes.md", contents)
    assert [log.timestamp_s for log in event.logs] == [0, 1, 2]
    assert all(log.metadata["inferred_time"] for log in event.logs)
    assert event.metadata["import_summary"]["time_basis"] == "row_index"
    assert event.metadata["import_summary"]["warnings"] == event.metadata["import_summary"]["notes"]
    assert any("not measured" in note for note in event.metadata["import_summary"]["notes"])
    assert event.states == [] and event.signals == []
    assert event.logs[1].level == "INFO"  # No diagnosis/severity invented from engineering prose.


def test_unlabelled_prose_is_not_misread_as_relative_time_or_state():
    event = build_event("notes.txt", b"2 sensitivity settings reviewed\n3 hours of notes retained\nstate: running\n")
    assert event.metadata["import_summary"]["time_basis"] == "row_index"
    assert event.states == [] and len(event.logs) == 3


def make_pdf(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    if text is not None:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_text_pdf_extracts_evidence_with_page_provenance():
    contents = make_pdf("[INFO] permit=ON")
    preview = inspect_upload("evidence.pdf", contents)
    assert preview["format"] == "pdf" and "permit=ON" in preview["text_preview"]
    event = build_event("evidence.pdf", contents)
    assert len(event.logs) == 1 and event.logs[0].metadata["source_page"] == 1
    assert event.states[0].name == "permit"
    assert any("OCR" in note for note in event.metadata["import_summary"]["notes"])


@pytest.mark.parametrize("contents,match", [(make_pdf(), "no extractable text"), (b"not a pdf", "PDF text could not")])
def test_unreadable_pdf_has_friendly_error(contents, match):
    with pytest.raises(ValueError, match=match):
        build_event("scan.pdf", contents)


@pytest.mark.parametrize("filename,contents,match", [
    ("../unsafe.csv", b"x\n1\n2", "filesystem path"),
    ("source.xlsx", b"data", "CSV, TSV, TXT"), ("empty.txt", b"", "empty"),
    ("binary.txt", b"\x00", "binary"), ("blank.txt", b" \n\n", "nonempty"),
    ("encoding.csv", b"\xff\xfe", "UTF-8"),
])
def test_upload_validation(filename, contents, match):
    with pytest.raises(ValueError, match=match):
        inspect_upload(filename, contents)


def test_upload_and_record_limits_reject_before_persistence(monkeypatch):
    from frib_ds.ingestion import common, narrative, tabular
    monkeypatch.setattr(common, "MAX_BYTES", 8)
    with pytest.raises(ValueError, match="20 MB"):
        inspect_upload("limit.txt", b"012345678")
    monkeypatch.setattr(common, "MAX_BYTES", 1024)
    monkeypatch.setattr(tabular, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="rows"):
        build_event("limit.csv", b"x\n1\n2\n")
    monkeypatch.setattr(narrative, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="nonempty lines"):
        build_event("limit.txt", b"one\ntwo\n")


def test_pdf_extracted_text_limit_is_actionable(monkeypatch):
    from frib_ds.ingestion import narrative
    monkeypatch.setattr(narrative, "MAX_BYTES", 5)
    with pytest.raises(ValueError, match="extracted text exceeds"):
        build_event("limit.pdf", make_pdf("a longer text line"))
