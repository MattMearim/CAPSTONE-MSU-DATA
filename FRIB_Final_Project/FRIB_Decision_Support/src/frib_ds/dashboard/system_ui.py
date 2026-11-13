"""Read-only machine inventory and explicit plans for the next application startup."""
from __future__ import annotations

import json

import streamlit as st

from frib_ds.dashboard.design import empty_state, info_card, page_header, section_header

HEALTHY_STATUSES = {"ok", "installed", "ready", "satisfied", "tested_branch", "local_source", "available"}


def _number(value, suffix=""):
    return f"{value:,.1f}{suffix}" if isinstance(value, (int, float)) else "Unavailable"


def _read_info(api_get, friendly_error):
    try:
        with st.spinner("Reading this computer and its software…"):
            result = api_get("/system/info")
        if not isinstance(result, dict) or not isinstance(result.get("components"), list):
            raise ValueError("The backend did not return a software inventory. Restart with Start FRIB.cmd to load the current version.")
        st.session_state["system_info"] = result
        st.session_state.pop("system_info_error", None)
    except Exception as exc:
        st.session_state["system_info_error"] = friendly_error(exc)


def _remember_choice(component_id, widget_key):
    choices = dict(st.session_state.get("system_component_choices", {}))
    choices[component_id] = st.session_state.get(widget_key, "keep")
    st.session_state["system_component_choices"] = choices


def _keep_view():
    if st.session_state.get("system_view") is None:
        st.session_state["system_view"] = "Required software"


def _pending(info):
    return (info.get("upgrade") or {}).get("pending")


def _queue(api_post, friendly_error, payload):
    try:
        if st.session_state.get("system_info_error"):
            raise ValueError("Refresh hardware and software successfully before queuing an update.")
        with st.spinner("Saving the startup update plan…"):
            result = api_post("/system/upgrades/plan", payload)
        if result.get("queued") is not True or not result.get("plan"):
            raise ValueError("The backend did not confirm a queued plan. Refresh status before retrying.")
        info = dict(st.session_state["system_info"])
        info["upgrade"] = {**info.get("upgrade", {}), "pending": result["plan"], "pending_error": None}
        st.session_state["system_info"] = info
        st.session_state["system_notice"] = "Update plan saved. Stop FRIB with Ctrl+C in its launcher window, then open Start FRIB.cmd to apply it."
        st.session_state.pop("system_action_error", None)
        st.rerun()
    except Exception as exc:
        st.session_state["system_action_error"] = friendly_error(exc)
        st.rerun()


def _cancel(api_delete, friendly_error):
    try:
        with st.spinner("Cancelling the queued update…"):
            result = api_delete("/system/upgrades/plan")
        if result.get("pending", "unconfirmed") is not None:
            raise ValueError("The backend did not confirm cancellation. Refresh status before retrying.")
        info = dict(st.session_state["system_info"])
        info["upgrade"] = {**info.get("upgrade", {}), "pending": None, "pending_error": None}
        st.session_state["system_info"] = info
        st.session_state["system_notice"] = "Queued update cancelled. Your installed software is unchanged."
        st.session_state.pop("system_action_error", None)
        st.rerun()
    except Exception as exc:
        st.session_state["system_action_error"] = friendly_error(exc)
        st.rerun()


def _hardware(info):
    hardware = info.get("hardware", {})
    cpu, memory = hardware.get("cpu") or {}, hardware.get("memory") or {}
    disk, gpu = hardware.get("disk") or {}, hardware.get("gpu") or {}
    columns = st.columns(4)
    with columns[0]:
        cores = cpu.get("logical_cores")
        info_card(cpu.get("model") or "Processor unavailable", f"{cores} logical cores" if cores else "Core count unavailable", hardware.get("architecture") or "Processor", "◈")
    with columns[1]:
        info_card(_number(memory.get("total_gib"), " GiB RAM"), f"{_number(memory.get('available_gib'), ' GiB')} available", "Memory", "▥")
    with columns[2]:
        info_card(_number(disk.get("free_gib"), " GiB free"), f"{_number(disk.get('total_gib'), ' GiB')} total", "Project drive", "▣")
    with columns[3]:
        devices = gpu.get("devices") or []
        info_card(devices[0].get("name", "Graphics adapter") if devices else "GPU availability unknown", gpu.get("note") or "GPU detection is an availability check, not a performance benchmark.", "Graphics", "◇")
    recommendations = info.get("recommendations") or {}
    with st.container(border=True, key="panel_system_suitability"):
        rationale = recommendations.get("rationale")
        if isinstance(rationale, list):
            rationale = " ".join(str(item) for item in rationale)
        info_card(str(recommendations.get("tier") or "Suitability unavailable").replace("_", " ").title(), rationale or "Refresh hardware status to assess real AI model capacity.", "Machine suitability", "✓")
        with st.expander("Hardware details"):
            st.caption(f"{hardware.get('os', 'Operating system unavailable')} · {hardware.get('os_version', '')} · Checked {info.get('checked_at', 'time unavailable')}")
            runtime = info.get("runtime") or {}
            if runtime.get("executable"):
                st.markdown("**Active interpreter**")
                st.code(str(runtime["executable"]), language=None)
                active_environment = runtime.get("active_environment")
                environment_label = active_environment.get("path") if isinstance(active_environment, dict) else active_environment
                st.caption(f"Python {runtime.get('python_version') or 'version unavailable'} · Environment: {environment_label or 'legacy private environment'}")
            st.caption("Memory and graphics availability can change while other applications run. Model suitability is an estimate.")
            for warning in recommendations.get("warnings") or []:
                st.caption(str(warning))
            st.json(hardware)


def _latest_map():
    return {item["id"]: item for item in st.session_state.get("system_versions", {}).get("versions", []) if item.get("id")}


def _software_status(component):
    version = component.get("installed_version")
    status = str(component.get("status") or "unknown").replace("_", " ")
    if not version and component.get("status") in {"available", "local_source"}:
        return f"{status.title()} · version unavailable"
    return f"Installed {version} · {status}" if version else f"Not installed · {status}"


def _component_card(component, latest, selectable=False):
    component_id = component["id"]
    with st.container(border=True, key=f"panel_system_component_{component_id}"):
        info_card(component.get("name") or component_id, component.get("purpose") or "Purpose details are unavailable from this backend.", _software_status(component), "□")
        if component.get("required") and component.get("status") in {"missing", "incompatible", "below_minimum"}:
            st.warning("This required component needs attention. Start FRIB.cmd checks and installs missing required software at startup.")
        if latest:
            if latest.get("latest_version"):
                st.caption(f"Latest checked release: {latest['latest_version']} · {str(latest.get('status', 'checked')).replace('_', ' ')}")
            else:
                st.caption("Latest release unavailable. The installed-version check remains available offline.")
        with st.expander("Version details and update options"):
            st.caption(f"Installed: {component.get('installed_version') or 'Not installed'} · Minimum: {component.get('minimum_version') or 'See component guidance'}")
            if latest:
                if latest.get("python_compatible") is False:
                    st.warning("The latest release does not support this Python version. Startup updates resolve compatible dependencies; this check does not pin that release.")
                if latest.get("error"):
                    st.caption(f"Version check: {latest['error']}")
                if latest.get("requires_python"):
                    st.caption(f"Latest release Python requirement: {latest['requires_python']}")
            available = component.get("choices") or []
            if selectable and component.get("upgradeable"):
                options = ["keep", *[choice["id"] for choice in available if choice.get("id")]]
                labels = {"keep": "Keep current version", **{choice["id"]: choice.get("label", choice["id"]) for choice in available if choice.get("id")}}
                saved = st.session_state.get("system_component_choices", {}).get(component_id, "keep")
                saved = saved if saved in options else "keep"
                widget_key = f"system_choice_{component_id}"
                chosen = st.selectbox("Startup update choice", options, index=options.index(saved), format_func=lambda value: labels[value], key=widget_key, on_change=_remember_choice, args=(component_id, widget_key))
                selected = next((choice for choice in available if choice.get("id") == chosen), None)
                if selected:
                    st.caption(selected.get("description") or "This update will run at the next startup.")
                    if not selected.get("enabled", False):
                        st.warning(selected.get("reason") or "This choice is not suitable for the current computer.")
            else:
                for choice in available:
                    st.write(choice.get("label") or "Component guidance")
                    st.caption(choice.get("description") or choice.get("reason") or "No automatic update is available for this component.")
                    if not choice.get("enabled") and choice.get("reason"):
                        st.caption(str(choice["reason"]))
            if component.get("guidance_url"):
                st.link_button("Open official component guidance", component["guidance_url"])


def _required_software(info, api_post, friendly_error):
    section_header("Required software", "The launcher checks core and dashboard dependencies and installs missing requirements automatically.")
    components = [component for component in info["components"] if component.get("required")]
    left, right = st.columns([2, 1])
    query = left.text_input("Find software", placeholder="Search component or purpose", key="system_component_search").strip().casefold()
    status = right.selectbox("Show software", ["All components", "Needs attention", "Installed"], key="system_component_filter")
    visible = [component for component in components if query in f"{component.get('name', '')} {component['id']} {component.get('purpose', '')}".casefold() and (status == "All components" or (status == "Installed" and component.get("status") in HEALTHY_STATUSES) or (status == "Needs attention" and component.get("status") not in HEALTHY_STATUSES))]
    latest = _latest_map()
    st.caption(f"{len(visible)} of {len(components)} required components")
    show_all = st.checkbox("Show all components", key="system_all_components") if len(visible) > 6 else False
    if not visible:
        empty_state("No matching software", "Change the search or status filter to see another component.")
    else:
        columns = st.columns(2)
        for index, component in enumerate(visible if show_all else visible[:6]):
            with columns[index % 2]:
                _component_card(component, latest.get(component["id"]), selectable=True)
    enabled = {component["id"] for component in components if component.get("upgradeable") and any(choice.get("id") == "upgrade" and choice.get("enabled") for choice in component.get("choices", []))}
    selected = [component_id for component_id, choice in st.session_state.get("system_component_choices", {}).items() if choice == "upgrade" and component_id in enabled]
    pending = bool(_pending(info))
    with st.container(border=True, key="panel_system_queue"):
        st.markdown("**Update at next startup**")
        st.caption("Changes are queued only. Stop the launcher with Ctrl+C, then open Start FRIB.cmd. Startup prepares and validates the replacement environment before using it.")
        if pending:
            st.info("A plan is already queued. Either update button below replaces that entire plan.")
        if selected:
            st.caption("Selected: " + ", ".join(selected))
        first, second = st.columns(2)
        if first.button("Replace plan with selected updates" if pending else "Queue selected updates", disabled=not selected or bool(st.session_state.get("system_info_error")), key="system_queue_selected", width="stretch"):
            _queue(api_post, friendly_error, {"mode": "selected", "components": [component_id for component_id in selected if component_id not in {"pip", "python"}], "upgrade_python": "python" in selected, "upgrade_pip": "pip" in selected, "include_semantic": False})
        if second.button("Replace plan with required updates" if pending else "Queue required updates", disabled=not enabled or bool(st.session_state.get("system_info_error")), key="system_queue_required", width="stretch"):
            _queue(api_post, friendly_error, {"mode": "required", "components": [], "upgrade_python": False, "upgrade_pip": False, "include_semantic": False})
        st.caption("Required updates keep the core, dashboard and real semantic embedding dependencies together. Language-model weights are managed separately by the launcher.")


def _ai_models(info, api_post, friendly_error):
    section_header("AI models", "Real language-model answers and semantic document embeddings are required for normal use. Check the configured providers and model capacity here.")
    recommendations = info.get("recommendations") or {}
    semantic_suitable = recommendations.get("semantic_suitable") is True
    local_suitable = recommendations.get("local_ai_suitable") is True
    a, b = st.columns(2)
    with a:
        info_card("Semantic document search", "Resources meet planning estimates" if semantic_suitable else "Confirm available memory and disk before model use", "Required embeddings", "⌕")
    with b:
        info_card("Local AI model", "Potentially suitable; model size still matters" if local_suitable else "Use a smaller real model or sufficient hardware", "Real model service", "◇")
    ai = info.get("ai") or {}
    if ai:
        st.caption(f"Answers: {ai.get('llm_provider', 'unavailable')} · {ai.get('llm_model', 'unavailable')}")
        st.caption(f"Embeddings: {ai.get('embedding_provider', 'unavailable')} · {ai.get('embedding_model', 'unavailable')}")
        if ai.get("configuration_error"):
            st.warning(str(ai["configuration_error"]))
    for component in [item for item in info["components"] if item["id"] in {"sentence-transformers", "ollama"}]:
        _component_card(component, _latest_map().get(component["id"]))
    semantic = next((item for item in info["components"] if item["id"] == "sentence-transformers"), None)
    can_queue = bool(semantic and any(choice.get("enabled") for choice in semantic.get("choices", [])))
    st.caption("This action queues semantic-search Python dependencies only. It does not download an AI model or install Ollama, and it does not switch the configured search or AI provider.")
    pending = bool(_pending(info))
    if pending:
        st.info("This action replaces the entire currently queued plan with semantic dependency updates.")
    if st.button("Replace plan with semantic dependencies" if pending else "Queue semantic dependencies", key="system_queue_semantic", disabled=not can_queue or bool(st.session_state.get("system_info_error")), width="stretch"):
        _queue(api_post, friendly_error, {"mode": "selected", "components": ["sentence-transformers"], "upgrade_python": False, "upgrade_pip": False, "include_semantic": False})
    if not can_queue:
        st.caption("Semantic dependency updates are unavailable until the backend confirms an enabled upgrade choice.")


def _startup_plan(info, api_delete, friendly_error):
    section_header("Startup plan", "Review pending changes and the result of the last startup update.")
    pending = _pending(info)
    pending_error = (info.get("upgrade") or {}).get("pending_error")
    if pending or pending_error:
        with st.container(border=True, key="panel_system_pending"):
            if pending_error:
                st.error(f"The saved update plan cannot be used: {pending_error}")
                st.caption("Cancel this saved plan, then create a new allowlisted selection.")
            else:
                info_card("Update queued", "Stop FRIB with Ctrl+C in the launcher window, then open Start FRIB.cmd. This dashboard does not install software while running.", "Next startup", "↻")
                components = pending.get("components") or []
                if pending.get("mode") == "required":
                    st.caption("Required software bundle")
                elif components:
                    st.caption("Selected components: " + ", ".join(str(value) for value in components))
                if pending.get("include_semantic"):
                    st.caption("Includes semantic-search dependencies.")
                if pending.get("upgrade_pip"):
                    st.caption("Includes pip update.")
                if pending.get("upgrade_python"):
                    st.caption("Includes a private Python runtime update.")
                with st.expander("Queued plan details"):
                    st.json(pending)
            if st.button("Cancel queued update", key="system_cancel", disabled=bool(st.session_state.get("system_info_error")), width="stretch"):
                _cancel(api_delete, friendly_error)
    else:
        info_card("No update queued", "Choose updates from Required software or AI models. Installed software stays unchanged until the next startup applies a plan.", "Next startup", "✓")
    result = (info.get("upgrade") or {}).get("last_result")
    if result:
        status = str(result.get("status") or "Recorded").replace("_", " ").title()
        info_card(status, result.get("message") or result.get("error") or "Inspect the recorded startup result for details.", "Last startup result", "•")
        if result.get("error"):
            st.warning(str(result["error"]))
        if result.get("previous_environment_retained"):
            st.caption("The previous working environment was retained. Resolve the reported issue before retrying the startup update.")
        with st.expander("Last startup result details"):
            st.json(result)
            st.caption("Startup writes its detailed installer log to .frib/setup.log in the project folder.")
    else:
        st.caption("No startup update result has been recorded yet.")


def render_system_page(api_get, api_post, api_delete, friendly_error):
    page_header("System & upgrades", "See what this computer can run, inspect software versions, and prepare updates for the next startup.", "APPLICATION MAINTENANCE")
    if "system_info" not in st.session_state and "system_info_error" not in st.session_state:
        _read_info(api_get, friendly_error)
    refresh, latest = st.columns(2)
    if refresh.button("Refresh hardware & software", key="system_refresh", width="stretch"):
        _read_info(api_get, friendly_error)
    info = st.session_state.get("system_info")
    if latest.button("Check latest versions", key="system_check_latest", disabled=not info, width="stretch", help="Explicitly checks the package index over the network. It does not install or queue updates."):
        try:
            with st.spinner("Checking available package releases…"):
                st.session_state["system_versions"] = api_post("/system/versions/check", {})
            st.session_state.pop("system_versions_error", None)
        except Exception as exc:
            st.session_state["system_versions_error"] = friendly_error(exc)
    if st.session_state.get("system_info_error"):
        st.warning(f"System status is unavailable: {st.session_state['system_info_error']}")
        st.caption("Open Start FRIB.cmd, then refresh. Hardware and installed-version checks use the local computer; the latest-release check needs a network connection.")
        if info:
            st.caption("Showing the last successful inventory. Refresh before preparing a new update plan.")
    if not info:
        empty_state("Connect to inspect this computer", "Start the backend to see hardware, installed software, and pending startup updates.")
        return
    if st.session_state.get("system_notice"):
        st.success(st.session_state.pop("system_notice"))
    if st.session_state.get("system_action_error"):
        st.error(f"Could not update the startup plan: {st.session_state['system_action_error']}")
    if st.session_state.get("system_versions_error"):
        st.info(f"Latest versions could not be checked: {st.session_state['system_versions_error']}. Installed software status remains available.")
    version_check = st.session_state.get("system_versions")
    if version_check:
        st.caption(f"Latest-release check: {version_check.get('checked_at', 'time unavailable')} · Package index · Informational; no update was installed or queued.")
    else:
        st.caption("Installed versions are checked locally. Latest releases have not been checked in this session.")
    if _pending(info):
        st.info("An update is queued for the next startup. Review or cancel it in Startup plan.")
    elif (info.get("upgrade") or {}).get("pending_error"):
        st.warning("A saved update plan needs attention. Open Startup plan to inspect or cancel it.")
    if (info.get("runtime") or {}).get("active_pointer_error"):
        st.warning(f"The managed environment pointer needs attention: {info['runtime']['active_pointer_error']}. Hardware details shows the interpreter currently serving this dashboard.")
    _hardware(info)
    view = st.segmented_control("System view", ["Required software", "AI models", "Startup plan"], default="Required software", key="system_view", label_visibility="collapsed", on_change=_keep_view) or "Required software"
    if view == "Required software":
        _required_software(info, api_post, friendly_error)
    elif view == "AI models":
        _ai_models(info, api_post, friendly_error)
    else:
        _startup_plan(info, api_delete, friendly_error)
    with st.expander("Download system report and inspect inventory"):
        st.caption("The report contains hardware details, package versions, queued changes and the latest-release result if requested.")
        report = {"inventory": info, "latest_release_check": version_check}
        st.download_button("Download system report (JSON)", json.dumps(report, indent=2, ensure_ascii=False, default=str), "frib_system_report.json", "application/json", key="system_report_download", width="stretch")
        st.json(info)
