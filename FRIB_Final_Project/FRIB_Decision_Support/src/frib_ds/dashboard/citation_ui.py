"""A read-only answer workspace with native, keyboard-accessible source selection."""
from __future__ import annotations

import hashlib
from html import escape
import json
import re
from collections.abc import Callable, Mapping
from pathlib import PurePath
from typing import Any
from urllib.parse import quote

import streamlit as st


_CITATION = re.compile(r"\[(S[1-9][0-9]*)\]")
_DOCUMENT_ID = re.compile(r"DOC-[A-Za-z0-9]{10,32}\Z")


def _text(value: Any, fallback: str = "") -> str:
    return str(value) if value is not None else fallback


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _paragraphs(answer: str) -> list[str]:
    """Keep fenced Markdown together while placing controls near cited paragraphs."""
    result, current = [], []
    fence = None
    for line in answer.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            candidate = marker.group(1)[0]
            fence = None if fence == candidate else candidate if fence is None else fence
        if not line.strip() and fence is None:
            if current:
                result.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        result.append("\n".join(current))
    return result


def _select_source(state_key: str, source_key: str) -> None:
    # Callbacks execute before the next render, so the panel changes on one click.
    state = dict(st.session_state.get(state_key, {}))
    state["selected"] = None if state.get("selected") == source_key else source_key
    st.session_state[state_key] = state


def passage_html(excerpt: str) -> str:
    """Highlight the supplied passage as text, never as executable document HTML."""
    return (
        '<div class="frib-citation-passage" style="white-space:pre-wrap;overflow-wrap:anywhere;'
        'line-height:1.7;padding:1rem;border-left:3px solid #856544;border-radius:8px;'
        'background:#fffaf0;color:#302b26">'
        '<mark style="background:#f7e7b5;color:inherit;box-decoration-break:clone;'
        '-webkit-box-decoration-break:clone;padding:0.12rem 0">'
        f'{escape(excerpt)}</mark></div>'
    )


def _source_label(source: Mapping[str, Any], index: int) -> str:
    label = _text(source.get("label"))
    return label if re.fullmatch(r"S[1-9][0-9]*", label) else f"S{index + 1}"


def render_draft_sources(relevant_sources: list, *, key_prefix: str) -> None:
    """Keep draft references behind native disclosure bubbles, without retrieval.

    Saved drafts may contain reference identifiers or historical metadata dicts.
    Preserve every supplied value inside the disclosure instead of guessing a
    document, hyperlink or excerpt from an unverified identifier.
    """
    references = relevant_sources if isinstance(relevant_sources, list) else []
    if not references:
        st.caption("No source references were saved with this draft.")
        return
    with st.container(horizontal=True, key=f"citation_bubbles_{key_prefix}_draft"):
        for index, reference in enumerate(references):
            with st.popover(f"S{index + 1}", key=f"{key_prefix}_draft_source_{index}",
                            help=f"Open saved source reference {index + 1}"):
                st.markdown(f"##### S{index + 1} · Saved source reference")
                if isinstance(reference, Mapping):
                    st.json(dict(reference))
                else:
                    st.text(_text(reference, "No source value recorded"))


def _original_document(source: Mapping[str, Any], *, ui_key: str, state_key: str,
                       api_get: Callable | None, api_download: Callable | None) -> None:
    document_id = _text(source.get("document_id"))
    if api_download is None:
        return
    if not _DOCUMENT_ID.fullmatch(document_id):
        st.caption("Original file link is unavailable for this saved source. Its excerpt remains visible.")
        return
    state = st.session_state[state_key]
    downloads = state.get("downloads", {})
    if st.button("Prepare original document", key=f"{ui_key}_prepare", help="Fetch the stored original file for download. This does not ask the AI again."):
        try:
            metadata = None
            if api_get is not None:
                inventory = api_get("/documents")
                if isinstance(inventory, list):
                    metadata = next((item for item in inventory if isinstance(item, Mapping) and item.get("document_id") == document_id), None)
            data = api_download(f"/documents/{quote(document_id, safe='')}/download")
            if not isinstance(data, bytes):
                raise ValueError("The original file could not be read.")
            filename = _text((metadata or {}).get("filename"), document_id)
            # A historical filename is a download name, never a local path.
            filename = PurePath(filename.replace("\\", "/")).name or document_id
            downloads = {**downloads, document_id: {"data": data, "filename": filename}}
            st.session_state[state_key] = {**state, "downloads": downloads}
        except Exception:
            st.warning("The original document is unavailable. It may have been removed, or the app service may be offline. The saved excerpt is still shown.")
    original = downloads.get(document_id)
    if original:
        st.download_button("Download original document", original["data"], file_name=original["filename"],
                           key=f"{ui_key}_download", on_click="ignore")


def render_rag_response(response: dict, *, key_prefix: str, api_get: Callable | None = None,
                        api_download: Callable | None = None) -> None:
    """Render saved response content; source selection never re-runs retrieval or AI.

    ``api_get`` and ``api_download`` are used only after the person presses
    Prepare original document. No API callback is needed to browse excerpts.
    ``key_prefix`` must identify this response's location on the current page.
    """
    response = response if isinstance(response, Mapping) else {}
    generation = response.get('generation')
    if isinstance(generation, Mapping) and generation.get('model'):
        st.caption(f"Generated with {generation.get('provider', 'AI')} · {generation['model']}")
    raw_sources = response.get("sources")
    raw_sources = raw_sources if isinstance(raw_sources, list) else []
    sources = [item for item in raw_sources if isinstance(item, Mapping)]
    fingerprint = _digest(response)
    state_key = f"{key_prefix}_citation_state"
    keyed = [(f"{index}_{_digest(source)}", source) for index, source in enumerate(sources)]
    source_keys = {key for key, _ in keyed}
    previous = st.session_state.get(state_key, {})
    if not isinstance(previous, Mapping) or previous.get("fingerprint") != fingerprint:
        previous = {"fingerprint": fingerprint, "selected": None, "downloads": {}}
    elif previous.get("selected") is not None and previous.get("selected") not in source_keys:
        previous = {**previous, "selected": None}
    st.session_state[state_key] = previous
    selected = previous.get("selected")
    widget_prefix = f"{key_prefix}_{fingerprint}"
    source_by_label = {}
    for index, (source_key, source) in enumerate(keyed):
        label = _text(source.get("label"))
        if re.fullmatch(r"S[1-9][0-9]*", label):
            source_by_label.setdefault(label, (source_key, source, index))

    evidence = response.get("evidence")
    if isinstance(evidence, list) and evidence:
        with st.container(border=True):
            st.markdown("#### Measured / derived evidence")
            st.caption("Recorded data and calculated findings, separate from procedure guidance and AI interpretation.")
            for item in evidence:
                st.write(_text(item))

    answer_col, source_col = st.columns([1.4, 1], gap="large")
    with answer_col:
        mode = response.get("mode", "llm")
        if mode == "extractive":
            st.info("Document search mode: these are retrieved passages. No AI interpretation was generated.")
            st.markdown("#### Retrieved procedure guidance")
        elif mode in {"unavailable", "insufficient_context"}:
            st.warning(_text(response.get("error")) or "There is not enough approved context to answer this question.")
            st.markdown("#### Search result")
        else:
            st.markdown("#### AI interpretation · requires human review")
            if not response.get("grounded"):
                st.warning("This answer has no verified supporting procedure context. Do not treat it as an operating instruction.")
        answer = _text(response.get("answer"))
        for paragraph_index, paragraph in enumerate(_paragraphs(answer)):
            st.markdown(paragraph)
            labels = list(dict.fromkeys(_CITATION.findall(paragraph)))
            available = [label for label in labels if label in source_by_label]
            if available:
                with st.container(horizontal=True, key=f"citation_bubbles_{widget_prefix}_paragraph_{paragraph_index}"):
                    for label in available:
                        source_key, source, _ = source_by_label[label]
                        st.button(label, key=f"{widget_prefix}_paragraph_{paragraph_index}_{label}",
                                  on_click=_select_source, args=(state_key, source_key),
                                  type="primary" if source_key == selected else "secondary",
                                  help=f"Open or close the retrieved passage from {_text(source.get('title'), 'Procedure')}")
        missing = sorted(set(_CITATION.findall(answer)) - set(source_by_label))
        if missing:
            st.warning("Source excerpt unavailable for " + ", ".join(f"[{label}]" for label in missing) + ". These citations cannot be checked in this saved response.")
        interpretation = _text(response.get("interpretation"))
        if interpretation and interpretation != answer:
            st.markdown("#### AI interpretation · requires human review")
            st.markdown(interpretation)

    with source_col:
        with st.container(border=True, key=f"citation_sources_{widget_prefix}"):
            st.markdown("#### Sources")
            if not sources:
                st.info("No approved document supports this response. Add approved references in Documents.")
                return
            with st.container(horizontal=True, key=f"citation_bubbles_{widget_prefix}_sources"):
                for index, (source_key, source) in enumerate(keyed):
                    st.button(_source_label(source, index), key=f"{widget_prefix}_source_{index}",
                              on_click=_select_source, args=(state_key, source_key),
                              type="primary" if source_key == selected else "secondary",
                              help=f"Open or close {_text(source.get('title'), 'Procedure')}")
            if selected is None:
                return
            source_key, source = next(item for item in keyed if item[0] == selected)
            index = next(index for index, item in enumerate(keyed) if item[0] == source_key)
            st.markdown(f"##### {_source_label(source, index)} · Retrieved procedure")
            st.write(_text(source.get("title")) or "Untitled saved source")
            page = source.get("page")
            page_label = f"Page {_text(page)}" if page is not None else "Page not recorded"
            st.caption(f"Revision {_text(source.get('version')) or 'not recorded'} · {page_label}")
            if source.get("section"):
                st.caption(f"Section: {_text(source['section'])}")
            excerpt = _text(source.get("excerpt"))
            if excerpt:
                st.markdown(passage_html(excerpt), unsafe_allow_html=True)
                st.caption("Highlighted text is the retrieved excerpt supplied with this answer. It may be shortened; check the original for surrounding context.")
            else:
                st.info("No excerpt was saved for this source. Check the original document if available.")
            with st.expander("Source details"):
                st.caption(f"Document ID: {_text(source.get('document_id')) or 'not recorded'}")
                st.caption(f"Chunk ID: {_text(source.get('chunk_id')) or 'not recorded'}")
            _original_document(source, ui_key=f"{widget_prefix}_{source_key}", state_key=state_key,
                               api_get=api_get, api_download=api_download)
