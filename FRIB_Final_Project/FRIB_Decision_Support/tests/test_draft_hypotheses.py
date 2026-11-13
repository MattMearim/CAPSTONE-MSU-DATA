"""End-to-end draft integration for deterministic, measured-evidence ordering."""
import hashlib
import json
from pathlib import Path

import pytest

from frib_ds.generator.registry import GeneratorRegistry
from frib_ds.knowledge.service import KnowledgeService
from frib_ds.processing.registry import ProcessorRegistry
from frib_ds.rag.llm import MockLLMProvider
from frib_ds.storage.files import EventFileStore
from frib_ds.storage.sqlite import SQLiteRepository


PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


@pytest.mark.parametrize("domain,patterns", [
    ("rf", ["cavity-field", "tuner-pressure", "reflected/forward-power"]),
    ("mechanical", ["increased vibration", "frequency-specific"]),
    ("plc", ["warning/interlock", "incomplete capture"]),
])
def test_mock_draft_integrates_ranked_domain_patterns_and_preserves_findings(tmp_path, domain, patterns):
    captured = GeneratorRegistry().for_domain(domain).generate(42)
    analysis = ProcessorRegistry().get(domain).process(captured)
    original_event = captured.model_dump(mode="json")
    original_findings = list(analysis.findings)
    files = EventFileStore(tmp_path / "events")
    original_path = files.save(captured)
    repo = SQLiteRepository(tmp_path / "drafts.db")
    repo.save_event(captured)
    repo.save_analysis(analysis)
    service = KnowledgeService(repo, MockLLMProvider(), PROMPTS, files)

    draft = service.create_draft(captured, analysis)

    assert draft.generated_by == "deterministic_fallback"
    assert draft.status == "draft"
    assert len(draft.hypotheses) >= len(patterns)
    assert [hypothesis.rank for hypothesis in draft.hypotheses] == list(range(1, len(draft.hypotheses) + 1))
    descriptions = [hypothesis.description for hypothesis in draft.hypotheses]
    for pattern in patterns:
        assert any(pattern in description for description in descriptions)
    assert all(description.startswith("Tentative review candidate:") for description in descriptions)
    assert all(hypothesis.support == "tentative_evidence_pattern" for hypothesis in draft.hypotheses)
    assert all(hypothesis.contradicting_evidence for hypothesis in draft.hypotheses)
    assert draft.observations == original_findings
    assert draft.evidence_snapshot["analysis"]["findings"] == original_findings
    method = draft.evidence_snapshot["hypothesis_ranking_method"].lower()
    assert "tentative" in method and "supporting observations" in method
    assert "not statistical confidence" in method and "confirmed cause" in method
    assert draft.evidence_snapshot["event_sha256"] == hashlib.sha256(original_path.read_bytes()).hexdigest()
    assert draft.evidence_snapshot["event_sha256_scope"] == "stored_original_event_json"
    assert captured.model_dump(mode="json") == original_event
    assert analysis.findings == original_findings
    assert repo.get_draft(draft.draft_id).model_dump(mode="json") == draft.model_dump(mode="json")
    assert repo.list_knowledge() == []
    json.dumps(draft.model_dump(mode="json"), allow_nan=False)


class RecordingMock(MockLLMProvider):
    def __init__(self):
        self.messages = []

    def chat(self, messages, json_schema=None):
        self.messages.append(messages)
        return super().chat(messages, json_schema)


@pytest.mark.parametrize("domain", ["rf", "mechanical", "plc"])
def test_synthetic_truth_cannot_change_draft_hypotheses_or_enter_model_prompt(tmp_path, domain):
    captured = GeneratorRegistry().for_domain(domain).generate(7)
    analysis = ProcessorRegistry().get(domain).process(captured)
    labeled = captured.model_copy(deep=True)
    sentinel = "FABRICATED_GROUND_TRUTH_MUST_NOT_INFLUENCE_THE_DRAFT"
    labeled.metadata["synthetic_ground_truth"] = {"root_cause": sentinel, "fault_frequency_hz": 99123, "trip_time_s": 98765}
    model = RecordingMock()
    service = KnowledgeService(SQLiteRepository(tmp_path / "drafts.db"), model, PROMPTS)

    ordinary = service.create_draft(captured, analysis)
    relabeled = service.create_draft(labeled, analysis)

    assert ordinary.generated_by == relabeled.generated_by == "deterministic_fallback"
    assert [hypothesis.model_dump() for hypothesis in ordinary.hypotheses] == [hypothesis.model_dump() for hypothesis in relabeled.hypotheses]
    assert ordinary.observations == relabeled.observations == analysis.findings
    assert ordinary.evidence_snapshot["hypothesis_ranking_method"] == relabeled.evidence_snapshot["hypothesis_ranking_method"]
    assert sentinel not in json.dumps(model.messages)
    assert "synthetic_ground_truth" not in json.dumps(model.messages)
    assert sentinel not in relabeled.summary
