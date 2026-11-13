"""Explore saved relationships in an offline 3D web; never create or review records."""
from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path
import re

import streamlit as st
import streamlit.components.v1 as components

from frib_ds.dashboard.design import empty_state, page_header


KINDS = {
    "event": "Dataset", "finding": "Finding", "document": "Procedure",
    "draft": "AI draft", "knowledge": "Reviewed knowledge", "domain": "Domain", "topic": "Topic",
}
VIEWS = {
    "All connections": set(KINDS),
    "Evidence & findings": {"event", "finding", "draft"},
    "Procedures": {"document"},
    "Reviewed knowledge": {"knowledge"},
}
_connection_web = components.declare_component(
    "frib_connections_web", path=str(Path(__file__).with_name("connections_component")),
)


def _text(value, limit=800):
    return str(value or "")[:limit]


def _plain_markdown(value):
    return re.sub(r"([\\`*_{}\[\]()#!|>~])", r"\\\1", _text(value))


def normalize_graph(payload):
    """Keep the viewer bounded and omit malformed or dangling relationships."""
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
        raise ValueError("The connection map could not be read. Refresh the workspace and try again.")
    nodes = {}
    for item in payload["nodes"][:500]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item.get("kind") not in KINDS:
            continue
        identifier = item["id"][:200]
        if identifier != item["id"] or identifier in nodes:
            continue
        nodes[identifier] = {
            "id": identifier, "kind": item["kind"], "label": _text(item.get("label") or KINDS[item["kind"]], 180),
            "summary": _text(item.get("summary") or item.get("description")), "status": _text(item.get("status"), 60),
            **{key: _text(item.get(key), 200) for key in ("record_id", "event_id", "domain", "version", "page") if item.get(key) is not None},
        }
    edges, seen = [], set()
    for item in payload["edges"][:1200]:
        if not isinstance(item, dict):
            continue
        source, target = item.get("source"), item.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in nodes or target not in nodes or source == target:
            continue
        kind = _text(item.get("kind") or item.get("relation"), 80)
        identity = source, target, kind
        if identity in seen:
            continue
        seen.add(identity)
        edges.append({"id": _text(item.get("id") or f"edge-{len(edges)}", 200), "source": source,
                      "target": target, "kind": kind, "label": _text(item.get("label") or kind.replace("_", " "), 180)})
    return list(nodes.values()), edges


def filter_graph(nodes, edges, query="", view="All connections"):
    """Retain one-hop context so matching ideas keep an explainable connection."""
    by_id = {node["id"]: node for node in nodes}
    adjacent = {identifier: set() for identifier in by_id}
    for edge in edges:
        adjacent[edge["source"]].add(edge["target"])
        adjacent[edge["target"]].add(edge["source"])
    seeds = {identifier for identifier, node in by_id.items() if node["kind"] in VIEWS.get(view, VIEWS["All connections"])}
    visible = seeds | {neighbor for identifier in seeds for neighbor in adjacent[identifier]}
    query = query.strip().casefold()
    if query:
        matching = {identifier for identifier in visible if query in " ".join(
            _text(by_id[identifier].get(key)) for key in ("label", "summary", "kind", "domain", "record_id", "event_id")
        ).casefold()}
        visible = matching | {neighbor for identifier in matching for neighbor in adjacent[identifier] if neighbor in visible}
    return [node for node in nodes if node["id"] in visible], [edge for edge in edges if edge["source"] in visible and edge["target"] in visible]


def select_node(identifier):
    st.session_state["connections_selected_id"] = identifier or None
    st.session_state["connections_jump"] = identifier or ""


def _jump_changed():
    st.session_state["connections_selected_id"] = st.session_state.get("connections_jump") or None


def clear_filters():
    st.session_state["connections_search"] = ""
    st.session_state["connections_view"] = "All connections"


def _go_to(page):
    st.session_state["main_nav"] = page


def _inspector(node, nodes, edges, callbacks):
    if node is None:
        st.markdown('<div class="connections-inspector-intro"><span>IN FOCUS</span><h3>Follow your curiosity.</h3>'
                    '<p>Choose a point in the web to see what it means, what connects to it, and where it came from.</p></div>', unsafe_allow_html=True)
        st.caption("You can also choose an item from the searchable list above.")
        return
    st.markdown(f'<div class="connections-inspector-intro"><span>{escape(KINDS[node["kind"]].upper())}</span>'
                f'<h3>{escape(node["label"])}</h3></div>', unsafe_allow_html=True)
    if node.get("status"):
        status = node["status"].replace("_", " ").capitalize()
        st.markdown(f'<span class="connections-status">{escape(status)}</span>', unsafe_allow_html=True)
    if node.get("summary"):
        st.text(node["summary"])
    detail = " · ".join(value for value in (node.get("record_id"), node.get("version")) if value)
    if detail:
        st.caption(_plain_markdown(detail))
    kind, event_id, record_id = node["kind"], node.get("event_id"), node.get("record_id")
    callback, argument, label = None, None, None
    if kind in {"event", "finding"} and event_id:
        callback, argument, label = callbacks["event"], event_id, "Open dataset"
    elif kind == "document" and record_id:
        callback, argument, label = callbacks["document"], record_id, "Open procedure"
    elif kind == "knowledge" and record_id:
        callback, argument, label = callbacks["knowledge"], record_id, "Open reviewed knowledge"
    elif kind == "draft" and event_id:
        callback, argument, label = callbacks["draft"], event_id, "Open review workspace"
    if callback:
        st.button(label, key="connections_open_record", on_click=callback, args=(argument,), type="primary", width="stretch")
    neighbors, by_id = [], {item["id"]: item for item in nodes}
    for edge in edges:
        if node["id"] in {edge["source"], edge["target"]}:
            neighbor = edge["target"] if node["id"] == edge["source"] else edge["source"]
            neighbors.append((by_id[neighbor], edge["label"]))
    st.divider()
    st.markdown(f"**Connected items · {len(neighbors)}**")
    if not neighbors:
        st.caption("This record has no saved links yet. It stays visible in the map.")
    for index, (neighbor, relationship) in enumerate(neighbors[:6]):
        st.caption(_plain_markdown(relationship))
        label = neighbor["label"] if len(neighbor["label"]) <= 76 else neighbor["label"][:73] + "…"
        st.button(_plain_markdown(label), key=f"connections_neighbor_{index}", on_click=select_node,
                  args=(neighbor["id"],), help=_plain_markdown(neighbor["label"]), width="stretch")
    if len(neighbors) > 6:
        st.caption("More connections are available in the connection list below.")


def render_connections_page(api_get, friendly_error, navigate_event, navigate_document, navigate_knowledge, navigate_review):
    page_header("See how it all connects.", "Explore the thread between your data, findings, procedures and the knowledge you keep.", "YOUR KNOWLEDGE IN 3D")
    try:
        payload = api_get("/connections")
        nodes, edges = normalize_graph(payload)
    except Exception as exc:
        st.error("Could not load your connection map. " + friendly_error(exc))
        if st.button("Retry connection map", key="connections_retry"):
            st.rerun()
        return
    if not nodes:
        empty_state("Your knowledge web starts here", "Add a dataset or a procedure. Saved findings and reviewed knowledge will connect as you work.")
        add, documents = st.columns(2)
        add.button("Add your data", key="connections_add_data", on_click=_go_to, args=("🧪 Create Dataset",), type="primary", width="stretch")
        documents.button("Open procedures", key="connections_documents", on_click=_go_to, args=("📁 Files & Documents",), width="stretch")
        return

    totals = Counter(node["kind"] for node in nodes)
    st.markdown('<div class="connections-overview">'
                f'<span><b>{len(nodes)}</b> connected ideas</span><span><b>{len(edges)}</b> saved relationships</span>'
                f'<span><b>{totals["knowledge"]}</b> reviewed lessons</span><span class="connections-local">● Saved in your workspace</span></div>', unsafe_allow_html=True)
    search, category, refresh = st.columns([2.7, 1.7, 0.8], vertical_alignment="bottom")
    query = search.text_input("Find an idea", placeholder="Search a dataset, procedure or topic…", key="connections_search")
    view = category.selectbox("Explore", list(VIEWS), key="connections_view")
    refresh.button("Refresh", key="connections_refresh", help="Read the latest saved relationships. This does not run AI.", width="stretch")
    visible_nodes, visible_edges = filter_graph(nodes, edges, query, view)
    visible_ids = {node["id"] for node in visible_nodes}
    if st.session_state.get("connections_selected_id") not in visible_ids:
        select_node(None)
    if st.session_state.get("connections_jump", "") not in visible_ids | {""}:
        st.session_state["connections_jump"] = ""
    if not visible_nodes:
        st.info("No connected ideas match this view. Try a different search or show all connections.")
        st.button("Clear filters", key="connections_clear_filters", on_click=clear_filters)
        return
    canvas, inspector = st.columns([3.2, 1.15], gap="medium")
    with canvas:
        focus = st.session_state.get("connections_focus", False)
        selected = st.session_state.get("connections_selected_id")
        result = _connection_web(nodes=visible_nodes, edges=visible_edges, selected_id=selected,
                                 focus_id=selected if focus else None, focus_enabled=bool(focus), motion_enabled=st.session_state.get("interface_motion", True),
                                 key="connections_web", default=None)
        if isinstance(result, dict) and result.get("nonce") != st.session_state.get("connections_last_nonce"):
            st.session_state["connections_last_nonce"] = result.get("nonce")
            picked = result.get("selected_id")
            if picked is None or isinstance(picked, str) and picked in visible_ids:
                changed = False
                if picked != selected:
                    select_node(picked)
                    changed = True
                if isinstance(result.get("focus"), bool) and result["focus"] != bool(focus):
                    st.session_state["connections_focus"] = result["focus"]
                    changed = True
                if changed:
                    st.rerun()
    with inspector:
        with st.container(border=True, key="connections_inspector"):
            by_id = {node["id"]: node for node in visible_nodes}
            st.selectbox("Jump to an item", ["", *sorted(visible_ids, key=lambda identifier: (by_id[identifier]["label"].casefold(), identifier))],
                         format_func=lambda identifier: "Choose an item…" if not identifier else f'{KINDS[by_id[identifier]["kind"]]} · {by_id[identifier]["label"]}',
                         key="connections_jump", on_change=_jump_changed,
                         help="A searchable, keyboard-accessible alternative to choosing a point in the web.")
            st.checkbox("Focus on the selected idea", key="connections_focus", help="Keep only its immediate neighborhood prominent in the 3D view.")
            _inspector(by_id.get(st.session_state.get("connections_selected_id")), visible_nodes, visible_edges,
                       {"event": navigate_event, "document": navigate_document, "knowledge": navigate_knowledge, "draft": navigate_review})
    st.caption("Lines describe saved relationships. Sharing a domain or topic does not establish a cause. AI drafts remain unreviewed until a person records a decision.")
    with st.expander("Connection list", expanded=False):
        if payload.get("truncated"):
            st.caption("Showing a compact view to keep the web responsive. Open an item to see its full saved details.")
        st.caption(f"Showing {len(visible_nodes)} ideas and {len(visible_edges)} relationships. Search results include their directly connected neighbors.")
        st.caption("The same relationships in a readable list. This view works without interacting with the 3D canvas.")
        if visible_edges:
            by_id = {node["id"]: node for node in visible_nodes}
            st.dataframe([{"From": by_id[edge["source"]]["label"], "Connection": edge["label"], "To": by_id[edge["target"]]["label"]}
                          for edge in visible_edges], hide_index=True, width="stretch")
        else:
            st.info("These records have no saved relationships yet. Choose an item above to inspect or open it.")
        notes = payload.get("notes")
        if isinstance(notes, list):
            for note in notes[:5]:
                if isinstance(note, str):
                    st.caption(_plain_markdown(note))
