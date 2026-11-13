"""A bounded, read-only map of relationships already saved in the workspace.

This module does not ask a model to invent links, load embeddings, or read
original evidence files. The pure builder also keeps browser-facing data small.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

MAX_RECORDS = 100
MAX_NODES = 500
MAX_EDGES = 1200
MAX_PAYLOAD_BYTES = 262_144
MAX_FINDINGS = 5
MAX_TAGS = 6
MAX_SOURCES = 10


def _text(value: Any, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    # Saved text remains plain text. Never return hidden control characters or
    # arbitrary nested objects coerced into strings for the browser to render.
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit]


def _identity(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _payload(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sources(draft: dict) -> list[dict]:
    snapshot = draft.get("evidence_snapshot")
    retrieval = snapshot.get("retrieval") if isinstance(snapshot, dict) else None
    sources = retrieval.get("sources") if isinstance(retrieval, dict) else None
    return [source for source in sources[:MAX_SOURCES] if isinstance(source, dict)] if isinstance(sources, list) else []


def read_connection_snapshot(repository, limit: int = 60) -> dict:
    """Project catalog data using one SQLite read transaction, never raw files.

    Large/malformed historical payloads retain their catalog nodes but omit
    optional details. Raw event samples, document text/vectors, audit records,
    reviewer identities and local filesystem paths are never selected.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RECORDS:
        raise ValueError(f"limit must be between 1 and {MAX_RECORDS}")
    uri = Path(repository.path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("events", "documents", "drafts", "knowledge", "analyses")}  # nosec B608: fixed table names
        # LIMIT is bound, and the projection bounds JSON parsing independently
        # of how large an event's original measurement capture is.
        safe_payload = f"CASE WHEN length(payload)<={MAX_PAYLOAD_BYTES} THEN payload END"
        drafts = [dict(row) for row in connection.execute(
            f"SELECT draft_id,event_id,status,{safe_payload} AS payload FROM drafts ORDER BY created_at DESC,draft_id LIMIT ?", (limit,))]
        knowledge = [dict(row) for row in connection.execute(
            f"SELECT knowledge_id,event_id,{safe_payload} AS payload FROM knowledge ORDER BY created_at DESC,knowledge_id LIMIT ?", (limit,))]
        references: list[str] = []
        for row in [*drafts, *knowledge]:
            payload = _payload(row["payload"])
            draft = payload.get("draft", {}) if "knowledge_id" in row else payload
            if isinstance(draft, dict):
                references.extend(_text(source.get("document_id"), 200) for source in _sources(draft))
        reference_ids = sorted(set(filter(None, references)))[:MAX_RECORDS * MAX_SOURCES * 2]
        documents: list[dict] = []
        if reference_ids:
            for offset in range(0, len(reference_ids), 400):
                batch = reference_ids[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                documents.extend(dict(row) for row in connection.execute(
                    f"SELECT document_id,title,version,approved,uploaded_at FROM documents WHERE document_id IN ({placeholders}) ORDER BY uploaded_at DESC,document_id LIMIT ?",
                    (*batch, limit)))
            documents.sort(key=lambda row: row["document_id"])
            documents.sort(key=lambda row: row["uploaded_at"], reverse=True)
            documents = documents[:limit]
            for row in documents:
                row.pop("uploaded_at", None)
        recent_documents = connection.execute("SELECT document_id,title,version,approved FROM documents ORDER BY uploaded_at DESC,document_id LIMIT ?", (limit,)).fetchall()
        seen = {row["document_id"] for row in documents}
        documents.extend(dict(row) for row in recent_documents if row["document_id"] not in seen)
        documents = documents[:limit]
        # Recent drafts and reviewed knowledge may refer to an older event.
        # Prefer those real parent records so their links remain navigable.
        event_ids = list(dict.fromkeys(row["event_id"] for row in [*drafts, *knowledge]))
        event_projection = "event_id,domain,event_type,CASE WHEN length(payload)<=1048576 AND json_valid(payload) THEN substr(json_extract(payload,'$.metadata.dataset_name'),1,120) END AS dataset_name"
        events: list[dict] = []
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            events = [dict(row) for row in connection.execute(
                f"SELECT {event_projection} FROM events WHERE event_id IN ({placeholders}) ORDER BY timestamp DESC,event_id LIMIT ?", (*event_ids, limit))]
        recent_events = connection.execute(f"SELECT {event_projection} FROM events ORDER BY timestamp DESC,event_id LIMIT ?", (limit,)).fetchall()
        seen_events = {row["event_id"] for row in events}
        events.extend(dict(row) for row in recent_events if row["event_id"] not in seen_events)
        events = events[:limit]
        analyses: list[dict] = []
        if events:
            selected_events = [row["event_id"] for row in events]
            placeholders = ",".join("?" for _ in selected_events)
            analyses = [dict(row) for row in connection.execute(
                f"SELECT event_id,{safe_payload} AS payload FROM analyses WHERE event_id IN ({placeholders}) ORDER BY created_at DESC,event_id LIMIT ?", (*selected_events, limit))]
        # Validate source references against the catalog's actual chunk pairing;
        # a saved free-text source label alone never creates a document link.
        chunk_pairs: set[tuple[str, str]] = set()
        pairs = {(source.get("document_id"), source.get("chunk_id"))
                 for row in [*drafts, *knowledge]
                 for payload in [_payload(row["payload"])]
                 for draft in [payload.get("draft", {}) if "knowledge_id" in row else payload]
                 if isinstance(draft, dict)
                 for source in _sources(draft)
                 if isinstance(source.get("document_id"), str) and isinstance(source.get("chunk_id"), str)}
        if pairs:
            chunk_ids = sorted({chunk_id for _, chunk_id in pairs})[:MAX_RECORDS * MAX_SOURCES * 2]
            # Stay below the parameter limit on older supported SQLite builds.
            for offset in range(0, len(chunk_ids), 400):
                batch = chunk_ids[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                chunk_pairs.update((row["document_id"], row["chunk_id"]) for row in connection.execute(
                    f"SELECT document_id,chunk_id FROM document_chunks WHERE chunk_id IN ({placeholders})", batch))
    return {"events": events, "documents": documents, "drafts": drafts, "knowledge": knowledge,
            "analyses": analyses, "chunk_pairs": chunk_pairs, "counts": counts, "limit": limit}


def build_connections(snapshot: dict) -> dict:
    """Build a small graph only from explicit IDs, saved findings and tags."""
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    clipped = False
    missing_references = 0
    omitted_details = 0

    def node(kind: str, record_id: str, label: str, **details) -> str | None:
        nonlocal clipped
        if not isinstance(record_id, str) or not record_id:
            return None
        identity = _identity(kind, record_id)
        if identity in nodes:
            return identity
        if len(nodes) >= MAX_NODES:
            clipped = True
            return None
        item = {"id": identity, "kind": kind, "record_id": _text(record_id, 200),
                "label": _text(label) or kind.title(), "summary": "", "status": "saved"}
        item.update({key: _text(value, 600 if key == "summary" else 200) for key, value in details.items() if isinstance(value, str)})
        nodes[identity] = item
        return identity

    def edge(source: str | None, target: str | None, kind: str, label: str) -> None:
        nonlocal clipped
        if source not in nodes or target not in nodes:
            return
        identity = _identity("edge", f"{source}|{kind}|{target}")
        if identity in edges:
            return
        if len(edges) >= MAX_EDGES:
            clipped = True
            return
        edges[identity] = {"id": identity, "source": source, "target": target, "kind": kind, "label": label}

    event_nodes: dict[str, str] = {}
    event_domains: dict[str, str] = {}
    for row in snapshot.get("events", [])[:MAX_RECORDS]:
        event_id = row.get("event_id")
        domain = _text(row.get("domain"), 80)
        event_type = _text(row.get("event_type"), 160)
        event = node("event", event_id, _text(row.get("dataset_name")) or event_type or event_id,
                     event_id=event_id, domain=domain, summary=f"Saved dataset: {event_type or 'event'}. Original measurements remain in Investigate Event.")
        if event:
            event_nodes[event_id] = event
            event_domains[event_id] = domain
        if domain and event:
            group = node("domain", domain, domain.upper() if domain.lower() in {"rf", "plc"} else domain.title(), status="category", summary="Shared saved domain. This is a category link, not a causal relationship.")
            edge(event, group, "in_domain", "Saved domain")

    document_nodes: dict[str, str] = {}
    for row in snapshot.get("documents", [])[:MAX_RECORDS]:
        document_id = row.get("document_id")
        approved = row.get("approved") in (True, 1)
        document = node("document", document_id, row.get("title") or "Untitled document", status="approved" if approved else "unapproved",
                        version=_text(row.get("version")), summary="Approved reference document." if approved else "Unapproved document. Excluded from AI retrieval.")
        if document:
            document_nodes[document_id] = document

    draft_nodes: dict[str, str] = {}
    pending_citations: list[tuple[str, dict]] = []
    pending_tags: list[tuple[str, dict]] = []

    def add_tags(owner: str, draft: dict) -> None:
        nonlocal clipped
        tags = draft.get("tags", [])
        if not isinstance(tags, list):
            return
        if len(tags) > MAX_TAGS:
            clipped = True
        for value in tags[:MAX_TAGS]:
            tag = _text(value, 80)
            if not tag:
                continue
            topic = node("topic", tag.casefold(), tag, status="tag", summary="A tag saved on this record. Shared tags do not establish a cause or verified similarity.")
            edge(owner, topic, "tagged_with", "Saved tag")

    for row in snapshot.get("drafts", [])[:MAX_RECORDS]:
        payload = _payload(row.get("payload"))
        if not payload:
            omitted_details += 1
        draft_id, event_id = row.get("draft_id"), row.get("event_id")
        status = row.get("status") if row.get("status") in {"draft", "approved", "corrected", "escalated"} else "unknown"
        summary = _text(payload.get("summary"), 600)
        draft = node("draft", draft_id, summary or "Knowledge draft", event_id=event_id,
                     domain=event_domains.get(event_id, ""), status=status, summary=summary or "Saved draft; optional details unavailable.")
        if draft:
            draft_nodes[draft_id] = draft
            edge(event_nodes.get(event_id), draft, "has_draft", "Saved knowledge draft")
            pending_citations.append((draft, payload))

    for row in snapshot.get("knowledge", [])[:MAX_RECORDS]:
        payload = _payload(row.get("payload"))
        draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        if not payload:
            omitted_details += 1
        event_id = row.get("event_id")
        # Never label a row approved solely because it is in the knowledge
        # table: retain the explicit human review decision and parent identity.
        decision = _text(review.get("decision"), 30)
        reviewed = (decision in {"approve", "correct"}
                    and draft.get("status") == {"approve": "approved", "correct": "corrected"}.get(decision)
                    and draft.get("event_id") == event_id and review.get("event_id") == event_id
                    and isinstance(draft.get("draft_id"), str) and bool(draft.get("draft_id"))
                    and review.get("draft_id") == draft.get("draft_id"))
        status = "approved" if reviewed and decision == "approve" else "corrected" if reviewed else "unverified"
        summary = _text(draft.get("summary"), 600)
        knowledge = node("knowledge", row.get("knowledge_id"), summary or "Reviewed knowledge", event_id=event_id,
                         domain=event_domains.get(event_id, ""), status=status, summary=summary or "Stored knowledge record; review details unavailable.")
        if knowledge:
            edge(event_nodes.get(event_id), knowledge, "has_knowledge", "Reviewed knowledge" if reviewed else "Stored knowledge record")
            if reviewed:
                edge(draft_nodes.get(draft.get("draft_id")), knowledge, "reviewed_as", "Human reviewed")
            pending_citations.append((knowledge, draft))
            pending_tags.append((knowledge, draft))

    # Core records take precedence over optional finding and tag nodes.
    for row in snapshot.get("analyses", [])[:MAX_RECORDS]:
        event_id = row.get("event_id")
        payload = _payload(row.get("payload"))
        findings = payload.get("findings", [])
        if not payload:
            omitted_details += 1
        if not isinstance(findings, list):
            continue
        if len(findings) > MAX_FINDINGS:
            clipped = True
        for index, finding in enumerate(findings[:MAX_FINDINGS]):
            text = _text(finding, 500)
            if not text or event_id not in event_nodes:
                continue
            point = node("finding", f"{event_id}:{index}", text, event_id=event_id,
                         domain=event_domains.get(event_id, ""), status="analysis", summary=text)
            edge(event_nodes.get(event_id), point, "has_finding", "Saved analysis finding")

    for draft_id, graph_id in draft_nodes.items():
        row = next((item for item in snapshot.get("drafts", [])[:MAX_RECORDS] if item.get("draft_id") == draft_id), {})
        pending_tags.append((graph_id, _payload(row.get("payload"))))
    for owner, draft in pending_tags:
        add_tags(owner, draft)

    chunk_pairs = snapshot.get("chunk_pairs", set())
    for owner, draft in pending_citations:
        sources = _sources(draft)
        retrieval = draft.get("evidence_snapshot", {})
        retrieval = retrieval.get("retrieval", {}) if isinstance(retrieval, dict) else {}
        all_sources = retrieval.get("sources", []) if isinstance(retrieval, dict) else []
        if isinstance(all_sources, list) and len(all_sources) > MAX_SOURCES:
            clipped = True
        for source in sources:
            document_id, chunk_id = source.get("document_id"), source.get("chunk_id")
            if not isinstance(document_id, str) or not isinstance(chunk_id, str):
                missing_references += 1
                continue
            if document_id not in document_nodes or (document_id, chunk_id) not in chunk_pairs:
                missing_references += 1
                continue
            edge(owner, document_nodes[document_id], "cites", "Saved source citation")

    shown = dict(Counter(item["kind"] for item in nodes.values()))
    counts = snapshot.get("counts", {})
    omitted_records = any(counts.get(key, 0) > len(snapshot.get(key, [])) for key in ("events", "documents", "drafts", "knowledge", "analyses"))
    notes = ["Links represent saved relationships, analysis findings and tags. They do not establish causation or operational instructions.",
             "Only source citations saved with a draft or reviewed knowledge appear. Unsaved AI Wiki conversations are not included."]
    if omitted_records or clipped:
        notes.append("This is a bounded view; some records or details are outside the current display limit.")
    if missing_references:
        notes.append("Some saved source references are unavailable, removed or outside this view; their links are omitted.")
    if omitted_details:
        notes.append("Some historical record details are malformed or exceed the safe preview size; their catalog nodes remain visible.")
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "counts": counts, "shown": shown,
            "truncated": bool(omitted_records or clipped or missing_references or omitted_details),
            "limits": {"records_per_kind": snapshot.get("limit", 60), "nodes": MAX_NODES, "edges": MAX_EDGES,
                       "findings_per_event": MAX_FINDINGS, "tags_per_record": MAX_TAGS, "sources_per_record": MAX_SOURCES},
            "missing_reference_count": missing_references, "omitted_detail_count": omitted_details, "notes": notes}


def workspace_connections(repository, limit: int = 60) -> dict:
    return build_connections(read_connection_snapshot(repository, limit))
