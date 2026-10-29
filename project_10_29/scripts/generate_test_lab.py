"""Reproduce clearly fictional, small evidence captures and procedure fixtures.

No application services are imported and no runtime data is changed. ReportLab
is optional: without it the two shipped, checked PDFs are copied unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-11T12:00:00Z"
NOTICE = "FICTIONAL TRAINING ONLY - not a FRIB operating procedure or real measurement."


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _table(path, header, rows, delimiter=","):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stream.getvalue().encode("utf-8"))


def _pdf(path, title, sections, project_relative):
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_LEFT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except ImportError:
        baseline = PROJECT / project_relative
        if not baseline.is_file():
            raise RuntimeError("PDF fixtures are missing. Generate once with ReportLab, or restore the shipped test-lab PDFs.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if baseline.resolve() != path.resolve():
            shutil.copyfile(baseline, path)
        return
    from xml.sax.saxutils import escape
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 22
    styles["Title"].leading = 26
    styles["Title"].textColor = colors.HexColor("#182632")
    styles["Title"].alignment = TA_LEFT
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 10.5
    styles["BodyText"].leading = 15
    styles["Heading2"].textColor = colors.HexColor("#087f8c")
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 12),
             Paragraph(escape(NOTICE), styles["BodyText"]), Spacer(1, 16)]
    for heading, paragraphs in sections:
        story.extend([Paragraph(escape(heading), styles["Heading2"]), Spacer(1, 5)])
        for paragraph in paragraphs:
            story.extend([Paragraph(escape(paragraph), styles["BodyText"]), Spacer(1, 8)])

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#617d8a"))
        canvas.drawString(46, 28, "FRIB decision-support test lab | Fictional | Rev LAB-1")
        canvas.drawRightString(566, 28, str(document.page))

    SimpleDocTemplate(str(path), pagesize=(612, 792), rightMargin=46, leftMargin=46,
                      topMargin=42, bottomMargin=50, title=title, author="Fictional Test Lab",
                      invariant=1).build(story, onFirstPage=footer, onLaterPages=footer)


def generate(destination: Path = PROJECT) -> dict:
    destination = Path(destination).resolve()
    data = destination / "sample_data" / "test_lab"
    docs = destination / "sample_docs" / "test_lab"
    data.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    datasets = []

    def case(case_id, filename, title, description, kind, options, expected, question, issue_codes=(), steps=None):
        datasets.append({"id": case_id, "title": title, "description": description,
            "path": f"sample_data/test_lab/{filename}", "filename": filename,
            "format": Path(filename).suffix[1:], "import_kind": kind,
            "options": {"event_id": f"LAB-{case_id}", "dataset_name": title,
                        "metadata": {"fictional": True, "captured_by": "Fictional Test Lab", "beam_state": "SIMULATION", "equipment": "LAB fixture"}, **options},
            "expected_outcome": expected.pop("outcome"), "expected_issue_codes": list(issue_codes),
            "expected": expected, "question": question,
            "steps": steps or ["Preview source quality and mapping.", "Review units and the validated event.", "Save explicitly, run analysis, then inspect the measured evidence."]})

    rf_rows = []
    for index in range(201):
        time = round(-0.6 + index * 0.005, 6)
        field = 10 if time < 0 else 10 * math.exp(-time / 0.025)
        reflected = 0.05 if time < 0 else 0.05 + 1.45 * math.exp(-time / 0.02)
        pressure = 2.0 if time < 0 else 2.1
        rf_rows.append([time, f"{field:.9g}", f"{reflected:.9g}", 2.0, pressure, "INACTIVE" if time < 0 else "ACTIVE"])
    _table(data / "rf_trip.csv", ["time_s", "cavity_field [MV/m]", "reflected_power [kW]", "forward_power [kW]", "tuner_pressure [kPa]", "RF_INTERLOCK"], rf_rows)
    rf_roles = {name: "numeric" for name in ["cavity_field [MV/m]", "reflected_power [kW]", "forward_power [kW]", "tuner_pressure [kPa]"]}
    case("RF-TRIP", "rf_trip.csv", "RF trip with recorded interlock", "A fictional field collapse with simultaneous reflected-power and tuner-pressure observations.", "mixed",
         {"domain": "rf", "column_roles": {**rf_roles, "RF_INTERLOCK": "category"}, "signal_names": {name: name.split(" [")[0] for name in rf_roles}},
         {"outcome": "Valid RF analysis: recorded reference at 0 s, 100 Pa pressure increase and approximately 25 ms field threshold crossing. Coincidence is not causation.", "valid": True, "processor": "rf_trip", "signals": 4,
          "units": {"cavity_field": "V/m", "reflected_power": "W", "forward_power": "W", "tuner_pressure": "Pa"},
          "features": {"trip_time_s": 0, "pressure_delta": 100, "approx_decay_ms": 25}, "feature_tolerance": 0.02, "review": "approve"},
         "RF cavity trip reflected power tuner pressure evidence review")

    _table(data / "field_emission.csv", ["time_ms", "gradient", "gradient_unit", "xray [counts/s]", "conditioning_phase"],
           [[i * 100, 5 + i / 4, "MV/m", 10 + i * 2, "SCAN_A" if i < 20 else "SCAN_B"] for i in range(41)])
    case("RF-XRAY", "field_emission.csv", "X-ray and gradient scan", "Two fictional gradient scans with increasing count-rate; descriptive correlation only.", "mixed",
         {"domain": "rf", "time_column": "time_ms", "time_unit": "ms", "column_roles": {"gradient": "numeric", "gradient_unit": "ignore", "xray [counts/s]": "numeric", "conditioning_phase": "category"}, "signal_names": {"xray [counts/s]": "xray"}, "unit_columns": {"gradient": "gradient_unit"}},
         {"outcome": "Gradient becomes V/m; X-ray remains counts/s. Scatter/trend plots describe co-variation without proving field emission or safe gradient.", "valid": True, "processor": "rf_field_emission_trends", "signals": 2,
          "units": {"gradient": "V/m", "xray": "counts/s"}, "features": {"xray_peak": 90, "gradient_min": 5e6, "gradient_max": 15e6, "xray_gradient_correlation": 1}, "feature_tolerance": 1e-6, "review": "escalate"},
         "RF X-ray gradient scan conditioning descriptive evidence limitations")

    cryo_rows = [[i, -269.0 + i * .01, 1000 + i * 2, "COOLDOWN", "[INFO] fictional cryogenic capture"] for i in list(range(12)) + list(range(16, 31))]
    _table(data / "cryo_temperature.csv", ["time_s", "helium_temperature [C]", "helium_pressure [mbar]", "mode", "note"], cryo_rows)
    case("CRYO", "cryo_temperature.csv", "Cryogenic temperature with capture gap", "Temperature offsets and pressure scaling with a deliberately omitted 12-15 s interval.", "mixed",
         {"domain": "other", "column_roles": {"helium_temperature [C]": "numeric", "helium_pressure [mbar]": "numeric", "mode": "category", "note": "log"}, "signal_names": {"helium_temperature [C]": "helium_temperature", "helium_pressure [mbar]": "helium_pressure"}, "quality_expectations": {"expected_interval_s": 1, "channels": {"helium_temperature": {"min": 4, "max": 4.3, "expected_stable": True, "stability_tolerance": .05}}}},
         {"outcome": "Celsius becomes kelvin and mbar becomes Pa; the capture gap and declared stability/bound differences are flagged. Generic evidence summary, no cryogenic diagnosis.", "valid": True, "processor": "mixed_evidence_summary", "signals": 2, "units": {"helium_temperature": "K", "helium_pressure": "Pa"}, "first_values": {"helium_temperature": 4.15, "helium_pressure": 100000}, "l2_codes": ["RECORDING_GAP", "STABILITY_EXCEEDED", "OUT_OF_BOUNDS"]},
         "Cryogenic helium temperature pressure capture gap evidence review")

    _table(data / "plc_sequence.csv", ["time_s", "PLC_STATE", "permit", "pressure [kPa]", "note"],
           [[i / 2, "RUNNING" if i < 8 else "WARNING" if i < 14 else "INTERLOCKED", "true" if i < 14 else "false", 2 + i * .01,
             "[INFO] Recorded state" if i < 8 else "[WARNING] Recorded warning" if i < 14 else "[ERROR] Recorded interlock"] for i in range(21)])
    case("PLC", "plc_sequence.csv", "PLC states, permit and log messages", "Chronological categorical state changes, boolean permit and explicit severity labels.", "mixed",
         {"domain": "plc", "column_roles": {"PLC_STATE": "category", "permit": "category", "pressure [kPa]": "numeric", "note": "log"}, "signal_names": {"pressure [kPa]": "pressure"}},
         {"outcome": "RUNNING -> WARNING -> INTERLOCKED is observed; transition times are 4 s and 7 s. Boolean permit remains categorical and all 21 text records survive.", "valid": True, "processor": "plc_sequence", "signals": 1, "logs": 21, "state_channels": ["PLC_STATE", "permit"], "log_levels": ["INFO", "WARNING", "ERROR"], "features": {"interlock_time_s": 7, "expected_sequence_observed": True}, "sequence": ["RUNNING", "WARNING", "INTERLOCKED"], "review": "correct"},
         "PLC RUNNING WARNING INTERLOCKED sequence permit log evidence review")

    _table(data / "mixed_units.tsv", ["datetime", "voltage", "voltage_unit", "temperature [F]", "pressure [kPa]", "fraction [%]", "note"],
           [["2026-10-11T12:00:00Z", 1000, "mV", 32, 1, 25, "[INFO] first record"], ["2026-10-11T12:00:01Z", 2, "kV", 68, "20 mbar", 50, "[WARNING] unit prefix changed"], ["2026-10-11T12:00:02Z", 500, "mV", 212, 1, 100, "[INFO] final record"]], delimiter="\t")
    case("UNITS", "mixed_units.tsv", "TSV with mixed scales and offset units", "Tab-separated UTF-8 data, ISO timestamps, per-row voltage units, Fahrenheit and percent.", "mixed",
         {"domain": "other", "time_column": "datetime", "time_unit": "datetime", "column_roles": {"voltage": "numeric", "voltage_unit": "ignore", "temperature [F]": "numeric", "pressure [kPa]": "numeric", "fraction [%]": "numeric", "note": "log"}, "signal_names": {"temperature [F]": "temperature", "pressure [kPa]": "pressure", "fraction [%]": "fraction"}, "unit_columns": {"voltage": "voltage_unit"}},
         {"outcome": "Voltage [1,2000,0.5] V, temperature [273.15,293.15,373.15] K, pressure [1000,2000,1000] Pa, fraction [0.25,0.5,1]. Original TSV bytes remain unchanged.", "valid": True, "processor": "mixed_evidence_summary", "signals": 4, "values": {"voltage": [1, 2000, .5], "temperature": [273.15, 293.15, 373.15], "pressure": [1000, 2000, 1000], "fraction": [.25, .5, 1]}, "units": {"voltage": "V", "temperature": "K", "pressure": "Pa", "fraction": "1"}},
         "Mixed units voltage temperature pressure normalization evidence")

    damaged = b"time_s,voltage [V],note\n0,1,keep first\n1,2,keep second\n1,2,keep second\n2,NA,keep missing\n3,broken,keep invalid text\n4,5,keep last\n5,6,extra,malformed\n6,7,keep final\n"
    (data / "damaged_capture.csv").write_bytes(damaged)
    repair = [{"operation": "drop_exact_duplicate_rows"}, {"operation": "mark_missing_tokens", "columns": ["voltage [V]"]}, {"operation": "drop_invalid_numeric_cells", "rows": [6], "columns": ["voltage [V]"]}, {"operation": "drop_malformed_rows", "rows": [8]}]
    case("REPAIR", "damaged_capture.csv", "Damaged capture requiring explicit repairs", "An exact duplicate, missing token, invalid numeric cell and malformed row; narrative cells must survive.", "mixed",
         {"domain": "other", "column_roles": {"voltage [V]": "numeric", "note": "log"}, "signal_names": {"voltage [V]": "voltage"}},
         {"outcome": "Raw import is blocked with no writes. Only the listed explicit repairs produce a valid copy. Original bytes and repair receipt remain downloadable; no missing measurements are filled.", "valid": False, "repaired_valid": True, "repair_options": {"_repairs": repair}, "processor": "mixed_evidence_summary", "repaired_values": {"voltage": [1, 2, 5, 7]}},
         "Missing measurements malformed rows preserve original evidence", ["row_shape", "duplicate_rows", "missing_tokens", "mixed_numeric_text"],
         ["Preview the blocked original.", "Select duplicate removal, missing-token marking, invalid cell row 6 and malformed row 8 explicitly.", "Re-preview; verify unchanged narrative and only four numeric measurements.", "Save and compare original and reviewed-copy downloads."])

    _table(data / "gap_jump_flatline.csv", ["time_s", "voltage [V]", "temperature [K]"],
           [[t, 1 if t < 8 else 15, 4.2] for t in [0, 1, 2, 3, 7, 8, 9, 10, 11, 12, 13, 14]])
    case("QUALITY", "gap_jump_flatline.csv", "Gap, jump and flatline expectations", "An omitted interval, abrupt voltage step and repeated temperature readings with explicit operator expectations.", "mixed",
         {"domain": "other", "column_roles": {"voltage [V]": "numeric", "temperature [K]": "numeric"}, "signal_names": {"voltage [V]": "voltage", "temperature [K]": "temperature"}, "quality_expectations": {"expected_interval_s": 1, "required_channels": ["voltage", "temperature", "vacuum"], "channels": {"voltage": {"max": 10, "expected_stable": True, "stability_tolerance": 2}, "temperature": {"flatline_samples": 5}}}},
         {"outcome": "Missing cadence/channel, voltage bound/stability and repeated-sample checks appear. They flag data/declared expectations and do not prove sensor failure or negligence.", "valid": True, "processor": "mixed_evidence_summary", "signals": 2, "l2_codes": ["RECORDING_GAP", "MISSING_CHANNEL", "OUT_OF_BOUNDS", "STABILITY_EXCEEDED", "FLATLINE_RUN", "BASELINE_CHANGE"]},
         "Voltage gap jump flatline required channel evidence review")

    _table(data / "incompatible_units.csv", ["time_s", "pressure [kPa]"], [[0, "1 V"], [1, "2 V"], [2, "3 V"]])
    case("BAD-UNIT", "incompatible_units.csv", "Incompatible physical dimensions", "Voltage suffixes contradict an explicitly pressure-valued header.", "mixed",
         {"domain": "other", "column_roles": {"pressure [kPa]": "numeric"}},
         {"outcome": "Validation blocks the incompatible V/Pa dimension; preview and failed save persist no event.", "valid": False},
         "Why are pressure and voltage units incompatible?", ["incompatible_units"])
    _table(data / "unsupported_dbm.csv", ["time_s", "rf_power [dBm]"], [[0, 10], [1, 11], [2, 12]])
    case("DBM", "unsupported_dbm.csv", "Unsupported logarithmic unit", "An explicit dBm header must not silently become W or dimensionless.", "mixed",
         {"domain": "other", "column_roles": {"rf_power [dBm]": "numeric"}},
         {"outcome": "Unsupported dBm is blocked. Convert outside this app with a reviewed reference and import a supported unit; do not relabel numeric readings as W.", "valid": False},
         "Unsupported logarithmic power units", ["unsupported_unit"])

    times = [round(i / 200, 6) for i in range(401)]
    vibration = [round((.02 if t < 1 else .15) * math.sin(2 * math.pi * 12 * t), 10) for t in times]
    mechanical = {"schema_version": "1.0", "event_id": "LAB-MECHANICAL", "domain": "mechanical", "event_type": "vibration_capture", "timestamp": STAMP,
        "metadata": {"fictional": True, "dataset_name": "Mechanical vibration native JSON", "equipment": "FICTIONAL-PUMP-1", "beam_state": "SIMULATION"},
        "signals": [{"name": "vibration", "unit": "m/s^2", "sample_rate_hz": 200, "timestamps_s": times, "values": vibration},
                    {"name": "bearing_temperature", "unit": "C", "sample_rate_hz": 20, "timestamps_s": [round(i / 20, 6) for i in range(41)], "values": [20 + i * .01 for i in range(41)]}],
        "states": [{"timestamp_s": 1, "name": "VIBRATION_ALARM", "value": "ACTIVE"}], "logs": [{"timestamp_s": 1, "level": "WARNING", "message": "Fictional recorded vibration alarm; cause unconfirmed.", "source": "test_lab"}], "attachments": [],
        "provenance": {"source": "fictional_test_lab", "generator_version": "1.0", "imported_by": "Fictional Test Lab", "notes": NOTICE}}
    _json(data / "mechanical.json", mechanical)
    case("MECHANICAL", "mechanical.json", "Mechanical vibration native JSON", "Native event with 200 Hz vibration and 20 Hz temperature channels; alignment preserves both originals.", "event", {},
         {"outcome": "Mechanical analysis observes approximately 12 Hz post-event oscillation and higher RMS. Temperature normalizes to K; alignment is derived and original grids remain unchanged.", "valid": True, "processor": "mechanical_vibration", "signals": 2, "units": {"vibration": "m/s^2", "bearing_temperature": "K"}, "features": {"anomaly_time_s": 1, "dominant_frequency_hz": 12}, "feature_tolerance": .2, "review": "approve"},
         "Mechanical vibration bearing temperature spectrum RMS evidence review")

    _table(data / "row_order.csv", ["voltage [V]", "state", "note"], [[i, "READY" if i < 3 else "RUN", "untimed fictional record"] for i in range(6)])
    case("UNTIMED", "row_order.csv", "Capture without measured timestamps", "Recorded sequence only; no physical cadence, FFT or event timing may be inferred.", "mixed",
         {"domain": "rf", "time_column": None, "time_unit": "row_index", "column_roles": {"voltage [V]": "numeric", "state": "category", "note": "log"}, "signal_names": {"voltage [V]": "voltage"}},
         {"outcome": "Unitless row order is explicit; generic evidence analysis is used for this incomplete RF capture, with no invented physical timing.", "valid": True, "processor": "mixed_evidence_summary", "signals": 1, "time_basis": "row_index"},
         "Untimed RF records evidence limitations")

    narrative = "\n".join(["2026-10-11T12:00:00Z [INFO] PLC_STATE=RUNNING permit=true Fictional shift capture started",
        "2026-10-11T12:00:04Z [WARNING] PLC_STATE=WARNING permit=true Operator observed a pressure trend",
        "2026-10-11T12:00:07Z [ERROR] PLC_STATE=INTERLOCKED permit=false Recorded interlock; cause unconfirmed",
        "2026-10-11T12:00:09Z [INFO] operator_action=REVIEW_ONLY No machine command issued"]) + "\n"
    (data / "operator_shift.log").write_text(narrative, encoding="utf-8")
    case("LOG", "operator_shift.log", "Timestamped operator log", "Explicit ISO timestamps, severity labels and name=value states with no numeric waveforms.", "text",
         {"domain": "plc"}, {"outcome": "Four source lines retained; PLC_STATE transitions support sequence analysis, but no unrecorded waveforms or physical cause are invented.", "valid": True, "processor": "plc_sequence", "signals": 0, "logs": 4, "state_channels": ["PLC_STATE", "permit", "operator_action"], "sequence": ["RUNNING", "WARNING", "INTERLOCKED"], "review": "escalate"},
         "PLC operator log permit chronological evidence limitations")

    evidence_pdf = "sample_data/test_lab/operator_note.pdf"
    _pdf(data / "operator_note.pdf", "Fictional operator evidence note", [
        ("Recorded observations", ["2026-10-11T12:00:00Z [INFO] Fictional operator noted stable indications.", "2026-10-11T12:00:04Z [WARNING] Fictional pressure trend was reported; no numeric value recorded.", "2026-10-11T12:00:07Z [ERROR] Fictional interlock was reported; physical cause remains unconfirmed."]),
        ("Evidence limits", ["This document is narrative evidence, not a procedure or waveform. PDF import preserves selectable text only; the title, headings and footer also become text records. Mixed timestamped and untimed lines therefore use explicit row order."])
    ], evidence_pdf)
    case("PDF-NOTE", "operator_note.pdf", "Selectable-text PDF evidence", "A real generated PDF containing narrative observations, headings and explicit evidence limitations.", "text", {"domain": "other"},
         {"outcome": "Selectable text is retained as logs with page provenance; mixed untimed headings mean explicit row-order coordinates. No OCR, image/table interpretation or numeric diagnosis.", "valid": True, "processor": "mixed_evidence_summary", "signals": 0, "time_basis": "row_index", "pdf_pages": True},
         "Fictional operator PDF reported pressure interlock evidence")

    procedures = []
    def procedure(item_id, filename, title, version, approved, body, question):
        if body is not None:
            (docs / filename).write_text(body, encoding="utf-8")
        procedures.append({"id": item_id, "path": f"sample_docs/test_lab/{filename}", "filename": filename,
            "title": title, "description": NOTICE, "version": version, "approved": approved,
            "question": question})
    rf_common = "RF cavity trip reflected power tuner pressure evidence review. Compare the recorded interlock timestamp with cavity field, forward power, reflected power and tuner pressure. Preserve original evidence and identify time/unit/capture limits. A coincident pressure change does not establish a root cause. Human review is required before reusable knowledge is approved."
    procedure("RF-A", "rf_trip_rev_a.md", "RF cavity trip evidence review", "LAB-A", True,
        f"# RF cavity trip evidence review - LAB-A\n\n{NOTICE}\n\n## Revision note\nLegacy fictional revision A. Review field and reflected power together.\n\n## Evidence review\n{rf_common}\n", "RF cavity trip reflected power tuner pressure evidence review")
    procedure("RF-B", "rf_trip_rev_b.md", "RF cavity trip evidence review", "LAB-B", True,
        f"# RF cavity trip evidence review - LAB-B\n\n{NOTICE}\n\n## Revision note\nFictional revision B adds explicit forward/reflected power comparison and original-file checksum verification.\n\n## Evidence review\n{rf_common}\n\n## Limits\nReview pre/post capture coverage. A descriptive decay crossing is not a fitted physical cavity parameter.\n", "RF cavity trip reflected power tuner pressure evidence review")
    procedure("RF-DRAFT", "rf_trip_draft_c.md", "RF cavity trip evidence review", "LAB-C-DRAFT", False,
        f"# RF cavity trip evidence review - unapproved draft C\n\n{NOTICE}\n\n{rf_common}\n\nDRAFT-ONLY-CANARY: this unapproved text must not appear among retrieved source excerpts.\n", "RF cavity trip reflected power tuner pressure evidence review")
    procedure("RF-XRAY", "rf_xray_scan.md", "RF X-ray gradient scan review", "LAB-1", True,
        f"# RF X-ray gradient scan review\n\n{NOTICE}\n\nX-ray gradient scan conditioning descriptive evidence limitations. Compare the recorded X-ray count-rate and cavity gradient on their shared captured interval. Report units, phase labels and missing coverage. Correlation does not establish field emission, conditioning effectiveness or a safe operating gradient. Escalate unresolved interpretations to a qualified reviewer.\n", "RF X-ray gradient scan conditioning descriptive evidence limitations")
    procedure("PLC", "plc_sequence.md", "PLC controls state sequence review", "LAB-1", True,
        f"# PLC controls state sequence review\n\n{NOTICE}\n\nPLC RUNNING WARNING INTERLOCKED sequence permit log evidence review. Preserve categorical and boolean values. Compare recorded state transitions and elapsed intervals with severity-labeled operator logs. Missing expected states may reflect incomplete capture or mapping. No machine action is authorized by this fictional checklist. Human correction or escalation is required when evidence is insufficient.\n", "PLC RUNNING WARNING INTERLOCKED sequence permit log evidence review")
    procedure("MECHANICAL", "mechanical_vibration.txt", "Mechanical vibration bearing review", "LAB-1", True,
        f"{NOTICE}\n\nMechanical vibration bearing temperature spectrum RMS evidence review.\nCompare native sample rates, overlapping time range and alarm timestamp. Report measured vibration RMS before/after the alarm and the derived spectrum with its units and frequency resolution. A spectral peak alone does not prove bearing damage. Review temperature context and missing coverage before assigning a cause.\n", "Mechanical vibration bearing temperature spectrum RMS evidence review")
    cryo_pdf = "sample_docs/test_lab/cryo_review.pdf"
    _pdf(docs / "cryo_review.pdf", "Fictional cryogenic evidence review", [
        ("Purpose and revision", ["LAB-1 | Approved status is a test metadata choice only. This fixture demonstrates PDF text extraction and cited retrieval, not facility approval."]),
        ("Cryogenic evidence checklist", ["Cryogenic helium temperature pressure capture gap evidence review. Verify recorded temperature and pressure source units. Celsius and Fahrenheit are offset scales; stored absolute temperatures use kelvin. Compare declared capture interval with missing timestamp ranges.", "Review measured channels against operator-declared bounds and stability tolerances. Differences flag evidence requiring review and do not establish equipment damage, negligence or a safe operating state."]),
        ("Human review and provenance", ["Preserve the original upload and checksum. Distinguish measured evidence, quoted procedure and tentative interpretation. Escalate unresolved cryogenic interpretations to a qualified human reviewer; this fictional document authorizes no machine action."])
    ], cryo_pdf)
    procedure("CRYO", "cryo_review.pdf", "Cryogenic helium temperature pressure review", "LAB-1", True, None, "Cryogenic helium temperature pressure capture gap evidence review")
    manifest = {"schema_version": "1.0", "fictional": True, "title": "FRIB decision-support fictional test lab",
        "description": NOTICE, "generated_reference_time": STAMP, "datasets": datasets, "procedures": procedures,
        "walkthrough": ["Download and import approved procedures individually; leave LAB-C-DRAFT unapproved.", "Import RF-TRIP, analyze, ask its suggested question and inspect citations/version metadata.", "Create a draft; verify no approved knowledge exists before named human review.", "Approve RF, correct PLC, escalate X-ray/log examples; compare knowledge outcomes.", "Try REPAIR/BAD-UNIT/DBM; blocked files must not create an event.", "Review CRYO/QUALITY gaps and declared expectations; inspect original bytes and derived-copy receipts.", "Compare two approved RF revisions. Current retrieval does not automatically supersede old versions; delete A explicitly to retire it."]}
    for entry in datasets + procedures:
        contents = (destination / entry["path"]).read_bytes()
        entry.update(size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest())
    _json(data / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT, help="Project-shaped fixture destination; never the runtime data directory.")
    args = parser.parse_args()
    manifest = generate(args.output)
    print(f"Generated {len(manifest['datasets'])} datasets and {len(manifest['procedures'])} procedures in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
