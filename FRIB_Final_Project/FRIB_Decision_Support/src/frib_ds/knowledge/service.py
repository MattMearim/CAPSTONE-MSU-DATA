from __future__ import annotations

import json
import uuid
import hashlib

from frib_ds.models import (
    EngineeringEvent,
    AnalysisResult,
    RAGResponse,
    KnowledgeDraft,
    ReviewRequest,
    ReviewRecord,
    KnowledgeRecord,
)
from frib_ds.rag.llm import LLMProvider, MockLLMProvider, model_identity
from frib_ds.storage.sqlite import SQLiteRepository
from frib_ds.knowledge.hypotheses import build_hypotheses


class KnowledgeGenerationUnavailable(RuntimeError):
    """A configured model failed; no substitute draft was saved."""


class KnowledgeService:
    def __init__(
        self,
        repo: SQLiteRepository,
        llm: LLMProvider,
        prompts_dir,
        files=None,
    ):
        self.repo = repo
        self.llm = llm
        self.prompts_dir = prompts_dir
        self.files = files

    def create_draft(
        self,
        event: EngineeringEvent,
        analysis: AnalysisResult,
        rag: RAGResponse | None = None
    ) -> KnowledgeDraft:

        draft_id = f"DRAFT-{uuid.uuid4().hex[:10].upper()}"

        analysis_observations = list(analysis.findings)

        source_labels = [
            f"{source.label}: {source.title}; document={source.document_id}; chunk={source.chunk_id}; version={source.version or 'unspecified'}; page={source.page}"
            for source in (rag.sources if rag else [])
        ]

        fallback_hypotheses = build_hypotheses(event, analysis)

        fallback_actions = [
            (
                "Review the measured and derived evidence together with the "
                "event timeline before assigning a cause."
            ),
            (
                "Compare the event timing with the applicable retrieved "
                "procedure and state/event logs."
            ),
            (
                "Have a qualified human reviewer confirm, correct, or "
                "escalate the draft before it becomes approved knowledge."
            ),
        ]

        fallback = KnowledgeDraft(
            draft_id=draft_id,
            event_id=event.event_id,
            summary=(
                f"{'Synthetic/demo ' if event.provenance.source == 'synthetic_generator' else ''}{event.domain} event "
                f"'{event.event_type}' was analyzed by {analysis.processor}. "
                "The available evidence requires human review before a "
                "confirmed cause can be assigned."
            ),
            observations=analysis_observations,
            hypotheses=fallback_hypotheses,
            recommended_actions=fallback_actions,
            affected_hardware=[str(event.metadata[key]) for key in ("cavity", "cryomodule", "equipment") if event.metadata.get(key)],
            relevant_sources=source_labels,
            tags=[str(event.domain), str(event.event_type)],
            status="draft",
            generated_by="deterministic_fallback"
        )

        schema = KnowledgeDraft.model_json_schema()

        payload = {
            "event": {"event_id": event.event_id, "domain": event.domain, "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(), "provenance": event.provenance.model_dump(),
                "metadata": {key: value for key, value in event.metadata.items() if key != "synthetic_ground_truth"},
                "states": [state.model_dump() for state in event.states[:200]],
                "logs": [{**log.model_dump(), "message":log.message[:1000]} for log in event.logs[:200]],
                "context_limits": {"state_records_in_prompt":min(200,len(event.states)), "total_state_records":len(event.states),
                    "text_records_in_prompt":min(200,len(event.logs)), "total_text_records":len(event.logs),
                    "text_characters_per_record":1000}},
            "analysis": analysis.model_dump(mode="json", exclude={"plot_specs"}),
            "rag": rag.model_dump(mode="json") if rag else None,
            "draft_id": draft_id,
        }

        try:
            system_path = f"{self.prompts_dir}/knowledge_system.txt"

            with open(system_path, encoding="utf-8") as file:
                system = file.read()

            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": system
                    },
                    {
                        "role": "user",
                        "content": (
                            "Create the draft from this JSON evidence:\n"
                            + json.dumps(payload)
                        )
                    },
                ],
                json_schema=schema
            )

            raw = raw.strip()

            if raw.startswith("```"):
                lines = raw.splitlines()

                if lines and lines[0].startswith("```"):
                    lines = lines[1:]

                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]

                raw = "\n".join(lines).strip()

            obj = json.loads(raw)

            obj["draft_id"] = draft_id
            obj["event_id"] = event.event_id
            obj["status"] = "draft"
            obj["generated_by"] = "configured_llm"
            # Identity, lifecycle state and timestamps belong to the application.
            # A model-supplied future date could otherwise pin this draft ahead
            # of every later human-requested draft in the event's history.
            obj["created_at"] = fallback.created_at

            draft = KnowledgeDraft.model_validate(obj)

            used_safe_completion = False

            if not draft.summary.strip():
                draft.summary = fallback.summary
                used_safe_completion = True

            if not draft.observations:
                draft.observations = list(fallback.observations)
                used_safe_completion = True

            if not draft.hypotheses:
                draft.hypotheses = [
                    hypothesis.model_copy(deep=True)
                    for hypothesis in fallback.hypotheses
                ]
                used_safe_completion = True

            if not draft.recommended_actions:
                draft.recommended_actions = list(
                    fallback.recommended_actions
                )
                used_safe_completion = True

            if not draft.relevant_sources and source_labels:
                draft.relevant_sources = list(source_labels)
                used_safe_completion = True

            if not draft.tags:
                draft.tags = list(fallback.tags)
                used_safe_completion = True

            if used_safe_completion:
                draft.generated_by = (
                    "configured_llm_with_deterministic_completion"
                )

        except Exception as exc:
            if not isinstance(self.llm, MockLLMProvider):
                raise KnowledgeGenerationUnavailable(
                    "The configured AI could not produce a valid knowledge draft. "
                    "Check the model service and model availability, then retry. "
                    "No replacement draft was created."
                ) from exc
            draft = fallback

        original_bytes = event.model_dump_json(indent=2).encode("utf-8")
        draft.generation = {} if isinstance(self.llm, MockLLMProvider) else model_identity(self.llm)
        checksum_scope = "canonical_event_model"
        if self.files is not None:
            try:
                original_bytes = self.files.original(event.event_id).read_bytes()
            except FileNotFoundError:
                # Older database imports may have no managed original. Hash the
                # available event model and label that narrower evidence scope;
                # never manufacture an original file or claim its byte hash.
                pass
            else:
                checksum_scope = "stored_original_event_json"
        draft.evidence_snapshot = {
            "event_id": event.event_id,
            "generation": dict(draft.generation),
            "event_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "event_sha256_scope": checksum_scope,
            "analysis": analysis.model_dump(mode="json", exclude={"plot_specs"}),
            "retrieval": rag.model_dump(mode="json") if rag else None,
            "hypothesis_ranking_method": (
                "Tentative patterns ordered by available supporting observations, then contradictions. This is not statistical confidence or a confirmed cause."
                if draft.generated_by == "deterministic_fallback" else
                "Model-suggested ordering is unvalidated and requires human review; ranks are not probabilities."
            ),
        }
        draft.hypotheses = [hypothesis.model_copy(update={"rank": rank}) for rank, hypothesis in enumerate(sorted(draft.hypotheses, key=lambda hypothesis: hypothesis.rank), 1)]
        # Measurements and actual source identifiers are supplied by the application.
        draft.observations = list(analysis_observations)
        draft.relevant_sources = list(source_labels)
        self.repo.save_draft(draft)

        return draft

    def review(
        self,
        draft: KnowledgeDraft,
        request: ReviewRequest
    ) -> tuple[ReviewRecord, KnowledgeRecord | None]:

        current = self.repo.get_draft(draft.draft_id)
        if current is None or current.status != "draft":
            raise ValueError("This draft has already been reviewed. Generate a new draft for another review.")
        draft = current
        final = draft.model_copy(deep=True)
        if request.decision.value == "correct":
            if request.corrected_draft is None or not request.corrected_draft.summary.strip():
                raise ValueError("A correction requires a nonempty corrected summary")
            final = request.corrected_draft.model_copy(deep=True)
            final.draft_id = draft.draft_id
            final.event_id = draft.event_id
            final.created_at = draft.created_at
            final.generated_by = draft.generated_by
            final.generation = dict(draft.generation)
            final.evidence_snapshot = draft.evidence_snapshot
            final.status = "corrected"
        elif request.decision.value == "escalate":
            final.status = "escalated"
        else:
            final.status = "approved"
        record = ReviewRecord(review_id=f"REV-{uuid.uuid4().hex[:10].upper()}",
            draft_id=draft.draft_id, event_id=draft.event_id, decision=request.decision,
            reviewer=request.reviewer, comments=request.comments)
        knowledge = None
        if final.status != "escalated":
            searchable = " ".join([final.summary, *final.observations,
                *[h.description for h in final.hypotheses], *final.recommended_actions,
                *final.affected_hardware, *final.tags])
            knowledge = KnowledgeRecord(knowledge_id=f"KNOW-{uuid.uuid4().hex[:10].upper()}",
                event_id=draft.event_id, draft=final, review=record, searchable_text=searchable)
        self.repo.commit_review(final, record, knowledge)
        return record, knowledge
