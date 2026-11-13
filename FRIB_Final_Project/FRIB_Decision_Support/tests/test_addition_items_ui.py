"""Merged utilities remain complete, independently selected and read-only on entry."""
from __future__ import annotations

import pytest

from frib_ds.dashboard.navigation import ADDITION_ITEMS, ADDITION_SECTIONS, LEGACY_SECTIONS
from test_dashboard_ui import APP, backend, open_page
from streamlit.testing.v1 import AppTest
from test_simple_workspace_ui import bundled_lab
from test_system_ui import system_backend
from test_workbench_ui import overview, workbench_backend


def control_keys(app):
    return {control.key for kind in (app.button, app.text_input, app.selectbox, app.segmented_control, app.number_input)
            for control in kind if control.key}


def test_sidebar_has_five_numbered_stages_and_one_compact_utilities_destination(backend):
    app = open_page("🏠 Home")
    assert app.radio(key="main_nav").options == [
        "Home", "1 · Add data", "2 · Explore an event", "3 · Documents",
        "4 · Ask a question", "5 · Review & approve", "Knowledge library",
        "Connections", "Addition items",
    ]
    assert not set(LEGACY_SECTIONS.values()).intersection(app.radio(key="main_nav").options)
    assert not backend["posts"] and not backend["deletes"]


@pytest.mark.parametrize("legacy,section", LEGACY_SECTIONS.items())
def test_saved_legacy_destination_migrates_before_the_main_navigation_renders(backend, system_backend, bundled_lab, legacy, section):
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["main_nav"] = legacy
    app.run()
    assert not app.exception
    assert app.radio(key="main_nav").value == ADDITION_ITEMS
    assert app.segmented_control(key="addition_section").value == section
    assert not backend["posts"] and not backend["deletes"]
    assert not system_backend["posts"] and not system_backend["deletes"]


def test_each_overview_section_renders_its_own_complete_controls(backend, system_backend, bundled_lab):
    app = open_page(ADDITION_ITEMS)
    selector = app.segmented_control(key="addition_section")
    assert selector.options == list(ADDITION_SECTIONS)
    expected = {
        "AI settings": {"ai_setup_view", "ai_picker_provider", "ai_picker_use"},
        "System status": {"system_component_search", "system_queue_selected", "system_check_latest"},
        "Settings": {"settings_units_value", "settings_units_from_time", "settings_units_to_time"},
        "Help": set(),
        "Try a new demo": {"test_lab_view", "lab_preview_case"},
    }
    for section in ADDITION_SECTIONS:
        backend["gets"].clear()
        before_inventory_reads = system_backend["reads"]
        app.segmented_control(key="addition_section").set_value(section).run()
        assert not app.exception
        assert app.radio(key="main_nav").value == ADDITION_ITEMS
        keys = control_keys(app)
        assert expected[section] <= keys
        for other, other_keys in expected.items():
            if other != section:
                assert not (other_keys & keys), f"Inactive {other} controls overwhelm {section}"
        if section == "Help":
            headings = [item.value for item in app.subheader]
            assert "From evidence to knowledge" in headings
            assert "What the labels mean" in headings
            assert any("getting started" in item.value.lower() for item in app.markdown)
        if section == "Settings":
            assert "/units" in backend["gets"] and "/audit" in backend["gets"]
        if section != "System status":
            assert system_backend["reads"] == before_inventory_reads
        if section != "Settings":
            assert "/audit" not in backend["gets"] and "/units" not in backend["gets"]
        assert not backend["posts"] and not backend["deletes"]
        assert not system_backend["posts"] and not system_backend["deletes"]


def test_sidebar_quick_guide_opens_help_in_the_same_overview(backend):
    app = open_page("🏠 Home")
    app.button(key="sidebar_quick_guide").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == ADDITION_ITEMS
    assert app.segmented_control(key="addition_section").value == "Help"
    assert not backend["posts"] and not backend["deletes"]


def test_demo_entry_callback_retains_the_selected_overview_section(workbench_backend, backend, bundled_lab):
    app = overview()
    app.button(key="overview_test_lab").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value == ADDITION_ITEMS
    assert app.segmented_control(key="addition_section").value == "Try a new demo"
    assert app.button(key="lab_preview_case")
    assert not backend["posts"] and not backend["deletes"]


def test_deselecting_an_overview_segment_keeps_an_explicit_default_selection(backend, system_backend):
    app = open_page("⚙️ Settings")
    app.segmented_control(key="addition_section").set_value(None).run()
    assert not app.exception
    assert app.segmented_control(key="addition_section").value == "System status"
    assert app.radio(key="main_nav").value == ADDITION_ITEMS
    assert "system_component_search" in control_keys(app)
    assert not backend["posts"] and not system_backend["posts"]
