"""Compact navigation and migration of saved utility-page destinations."""
ADDITION_ITEMS = "🧰 Addition items"
ADDITION_SECTIONS = ("System status", "AI settings", "Settings", "Help", "Try a new demo")
ADDITION_DESCRIPTIONS = {
    "AI settings": "Choose a model, automate setup for your hardware, or see live resource usage.",
    "System status": "Hardware, required software, AI models, startup update plans and downloadable inventory.",
    "Settings": "Service connection, measurement unit conversion and recorded activity.",
    "Help": "Written getting-started guidance and explanations of evidence labels. The interactive tutorial lives on Home.",
    "Try a new demo": "Fictional datasets, matching procedures, import presets and expected outcomes.",
}
LEGACY_SECTIONS = {
    "⚙️ AI Settings": "AI settings",
    "🖥️ System & upgrades": "System status", "⚙️ Settings": "Settings",
    "❓ Help": "Help", "🧰 Test Lab": "Try a new demo",
}


def select_destination(state, target):
    if target in LEGACY_SECTIONS:
        state["addition_section"] = LEGACY_SECTIONS[target]
        target = ADDITION_ITEMS
    state["main_nav"] = target


def normalize_navigation(state):
    target = state.get("main_nav")
    if target in LEGACY_SECTIONS:
        select_destination(state, target)


def keep_addition_section():
    import streamlit as st
    if st.session_state.get("addition_section") not in ADDITION_SECTIONS:
        st.session_state["addition_section"] = "System status"
