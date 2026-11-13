"""Discover bundled fictional examples; browsing and previews never save records."""
from __future__ import annotations

import io
import json
import mimetypes
from pathlib import Path, PurePosixPath
import stat
import zipfile

import streamlit as st

from frib_ds.dashboard.design import info_card, page_header, section_header
from frib_ds.dashboard.quality_ui import render_quality_report


def project_root() -> Path:
    # Same source/install configuration lookup used by the one-click launcher.
    from frib_ds.config import get_config
    return get_config().config_dir.parent


def lab_file(project: Path, relative: str) -> Path:
    # This value also becomes a ZIP member name. Reject traversal even when its
    # final resolved location happens to return to an allowed fixture folder.
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or "\0" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or PurePosixPath(relative).is_absolute()):
        raise ValueError("The bundled example must use a plain relative fixture path.")
    project = project.resolve()
    raw = project / relative
    current = project
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            details = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("The bundled example must not redirect through a link.")
    path = raw.resolve()
    allowed = [project / name / "test_lab" for name in ("sample_data", "sample_docs")]
    if not any(path.is_relative_to(root) for root in allowed) or not path.is_file():
        raise ValueError("The bundled example is missing or outside the Test Lab folders.")
    return path


def example_preview(case: dict, contents: bytes, api_post) -> dict:
    if case["import_kind"] == "event":
        from frib_ds.models import EngineeringEvent
        from frib_ds.units import normalize_event_units
        from frib_ds.quality import assess_event
        original = EngineeringEvent.model_validate_json(contents)
        event = normalize_event_units(original)
        quality = assess_event(event, event.metadata.get("quality_expectations"))
        event.metadata["data_quality"] = quality
        return {"event": event.model_dump(mode="json"), "validation": {"valid": True, "errors": []},
                "quality": {"l2": quality}, "original_event": original.model_dump(mode="json")}
    return api_post("/ingestion/preview",
                    files={"file": (case.get("import_filename") or case["filename"], contents, "application/octet-stream")},
                    data={"options": json.dumps(case.get("options", {})), "validate": "true"})


def bundle_examples(project: Path, manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample_data/test_lab/manifest.json", json.dumps(manifest, indent=2))
        for item in [*manifest["datasets"], *manifest["procedures"]]:
            path = lab_file(project, item["path"])
            archive.writestr(item["path"], path.read_bytes())
        guide = project / "docs" / "TEST_LAB.md"
        if guide.is_file():
            archive.writestr("TEST_LAB.md", guide.read_bytes())
    return buffer.getvalue()


def render_test_lab(api_get, api_post, friendly_error, navigate_event, plot_event, clear_answers):
    page_header("A place to try everything.", "Explore fictional evidence, see the expected result, and test a complete investigation.", "TEST LAB")
    st.caption("Synthetic examples only. Browsing and previewing leave your saved workspace unchanged.")
    try:
        project = project_root()
        manifest = json.loads(lab_file(project, "sample_data/test_lab/manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        st.error(f"Could not load the bundled Test Lab: {friendly_error(exc)}")
        return
    view = st.segmented_control("Explore the Test Lab", ["Datasets", "Procedures", "Walkthrough"], default="Datasets", key="test_lab_view") or "Datasets"
    if view == "Datasets":
      with st.container():
        cases = manifest["datasets"]
        by_id = {case["id"]: case for case in cases}
        case_id = st.selectbox("Choose a test scenario", list(by_id), format_func=lambda value: by_id[value]["title"], key="test_lab_case")
        case = by_id[case_id]
        contents = lab_file(project, case["path"]).read_bytes()
        left, right = st.columns([1.2, 1], gap="large")
        with left:
          with st.container(border=True, key="panel_lab_case"):
            info_card(case["title"], case.get("description", ""), case["format"].upper() + " · Fictional evidence", "∿")
            section_header("What to look for")
            st.write(case.get("expected_outcome", "Review the evidence and its quality findings."))
            if case.get("question"):
                st.caption("Try asking: " + case["question"])
            if case.get("options", {}).get("_repairs"):
                st.info("This example includes an explicit repair preset. Preview uses a derived copy and preserves the original bytes.")
            st.download_button("Download this dataset", contents, file_name=case["filename"], key=f"lab_download_{case_id}", width="stretch")
            if st.button("Preview this example", type="primary", key=f"lab_preview_{case_id}", width="stretch"):
                try:
                    with st.spinner("Checking evidence and units…"):
                        st.session_state[f"lab_result_{case_id}"] = example_preview(case, contents, api_post)
                except Exception as exc:
                    st.error(f"The example could not be previewed: {friendly_error(exc)}")
        with right:
          with st.container(border=True, key="panel_lab_steps"):
            section_header("Try it step by step")
            for index, step in enumerate(case.get("steps", []), 1):
                info_card(str(step), eyebrow=f"Step {index}")
            with st.expander("Preset mapping and expected issue codes"):
                st.json({"options": case.get("options", {}), "expected_l1_issue_codes": case.get("expected_issue_codes", []),
                         "expected_l2_issue_codes": case.get("expected", {}).get("l2_codes", [])})
        result = st.session_state.get(f"lab_result_{case_id}")
        if result:
            validation = result.get("validation", {})
            for stage in ("l1", "l2"):
                if result.get("quality", {}).get(stage):
                    render_quality_report(result["quality"][stage], f"lab_{case_id}_{stage}", f"{stage.upper()} · Example quality", expanded=True)
            if validation.get("valid") and result.get("event"):
                st.success("Preview is ready. Nothing has been saved.")
                plot_event(result["event"], prefix=f"lab_{case_id}")
                if st.button("Save example to my workspace", key=f"lab_save_{case_id}", width="stretch"):
                    try:
                        if case["import_kind"] == "event":
                            saved = api_post("/events", result["original_event"])
                            event_id = saved["event_id"]
                            try:
                                api_post(f"/events/{event_id}/files", files={"file": (case["filename"], contents, "application/json")})
                            except Exception as exc:
                                st.warning(f"Event saved, but the source attachment was not preserved: {friendly_error(exc)}")
                        else:
                            saved = api_post("/ingestion/import", files={"file": (case.get("import_filename") or case["filename"], contents)}, data={"options": json.dumps(case.get("options", {}))})
                            event_id = saved["event"]["event_id"]
                        st.session_state[f"lab_saved_{case_id}"] = event_id
                        from frib_ds.dashboard.workflow_ui import remember_event
                        remember_event(event_id, case.get("title"))
                        st.success(f"Saved fictional example {event_id}.")
                    except Exception as exc:
                        st.error(f"Could not save this example: {friendly_error(exc)}")
            else:
                st.warning("This example is blocked. Use its downloaded source in Data workspace to review and explicitly select repairs.")
                for error in validation.get("errors", []):
                    st.caption(str(error))
            if st.session_state.get(f"lab_saved_{case_id}"):
                st.button("Open this investigation", key=f"lab_open_{case_id}", on_click=navigate_event, args=(st.session_state[f"lab_saved_{case_id}"],), width="stretch")
    if view == "Procedures":
      with st.container():
        by_id = {item["id"]: item for item in manifest["procedures"]}
        identifier = st.selectbox("Choose a fictional procedure", list(by_id),
            format_func=lambda value: f"{by_id[value]['title']} · {by_id[value].get('version', 'No revision')} · "
                + ("Approval exercise" if by_id[value].get("approved") else "Unapproved draft"), key="lab_procedure")
        item = by_id[identifier]
        contents = lab_file(project, item["path"]).read_bytes()
        info_card(item["title"], item.get("description", ""), f"{item.get('version', 'No revision')} · Fictional training document", "≡")
        st.caption("Retrieval test: " + item.get("question", "Ask about this document after importing it."))
        st.download_button("Download this procedure", contents, item["filename"], key=f"lab_proc_download_{identifier}")
        approved = False
        if item.get("approved"):
            approved = st.checkbox("Use this fictional document as approved guidance in this demo workspace", key=f"lab_approve_{identifier}")
        else:
            st.info("This draft is a negative retrieval test. It will be stored for reference and excluded from assistant answers.")
        if st.button("Add procedure to my library", key=f"lab_add_procedure_{identifier}", disabled=bool(item.get("approved")) and not approved, type="primary"):
            try:
                indexed = api_post("/documents/index", files={"file": (item["filename"], contents, mimetypes.guess_type(item["filename"])[0] or "application/octet-stream")}, data={"title": item["title"], "version": item.get("version", ""), "approved": str(approved).lower()})
                st.success(f"Added fictional procedure · {indexed.get('indexed_chunks', 0)} searchable excerpts.")
                clear_answers()
            except Exception as exc:
                st.error(f"Could not add the procedure: {friendly_error(exc)}")
        if item["filename"].lower().endswith((".md", ".txt")):
            with st.expander("Read the source document"):
                st.text(contents.decode("utf-8"))
    if view == "Walkthrough":
      with st.container():
        section_header("Present the complete workflow")
        for index, step in enumerate(manifest.get("walkthrough", []), 1):
            info_card(str(step), eyebrow=f"Step {index}")
        st.code('& ".\\Run Test Lab.cmd"', language="powershell")
        st.caption("The automated runner uses disposable storage and reports actual checks for ingestion, quality, analysis, procedure retrieval and human review.")
    with st.expander("Take the test files with you"):
        st.download_button("Download all examples and instructions", bundle_examples(project, manifest), "FRIB_Test_Lab.zip", "application/zip", key="lab_bundle")


