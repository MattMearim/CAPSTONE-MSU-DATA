from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Provenance(BaseModel):
    source: str
    generator_version: str | None = None
    imported_by: str | None = None
    checksum: str | None = None
    notes: str | None = None

class Signal(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str
    unit: str = ""
    sample_rate_hz: float = Field(gt=0)
    timestamps_s: list[float]
    values: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamps_s", "values", mode="before")
    @classmethod
    def no_boolean_measurements(cls, value):
        if isinstance(value, (list,tuple)) and any(isinstance(item,bool) for item in value):
            raise ValueError("True/false values belong in a categorical state column, not numeric measurements or timestamps")
        return value

    @model_validator(mode="after")
    def validate_samples(self):
        if len(self.timestamps_s) != len(self.values) or len(self.values) < 2:
            raise ValueError("Each signal needs at least two samples and equal timestamp/value lengths")
        if any(b <= a for a, b in zip(self.timestamps_s, self.timestamps_s[1:])):
            raise ValueError("Signal timestamps must be strictly increasing; sort and remove duplicate times before import")
        return self

class StateEvent(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    timestamp_s: float
    name: str
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class LogEntry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    timestamp_s: float
    level: str = "INFO"
    message: str
    source: str = "synthetic"
    metadata: dict[str, Any] = Field(default_factory=dict)

class EngineeringEvent(BaseModel):
    schema_version: str = "1.0"
    event_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    domain: str
    event_type: str
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    signals: list[Signal] = Field(default_factory=list)
    states: list[StateEvent] = Field(default_factory=list)
    logs: list[LogEntry] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def validate_event(self):
        names = [signal.name for signal in self.signals]
        if len(names) != len(set(names)):
            raise ValueError("Signal names must be unique within an event")
        if self.event_id.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise ValueError("Event ID is a reserved Windows filename")
        return self

class TimelineItem(BaseModel):
    timestamp_s: float
    event: str
    evidence: str | None = None

class AnalysisResult(BaseModel):
    event_id: str
    processor: str
    processor_version: str
    features: dict[str, Any] = Field(default_factory=dict)
    timeline: list[TimelineItem] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    plot_specs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    text: str
    page: int | None = None
    section: str | None = None
    version: str | None = None
    approved: bool = False
    source_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class RAGSource(BaseModel):
    label: str
    title: str
    document_id: str
    chunk_id: str
    page: int | None = None
    section: str | None = None
    score: float | None = None
    excerpt: str | None = None
    version: str | None = None

class RAGResponse(BaseModel):
    question: str
    answer: str
    sources: list[RAGSource] = Field(default_factory=list)
    grounded: bool = False
    event_id: str | None = None
    mode: str = "insufficient_context"
    error: str | None = None
    evidence: list[str] = Field(default_factory=list)
    interpretation: str | None = None

class Hypothesis(BaseModel):
    rank: int = Field(ge=1)
    description: str
    support: str = "unknown"
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)

class KnowledgeDraft(BaseModel):
    draft_id: str
    event_id: str
    summary: str
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    affected_hardware: list[str] = Field(default_factory=list)
    relevant_sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    generated_by: str = "deterministic_fallback"
    created_at: datetime = Field(default_factory=utcnow)
    evidence_snapshot: dict[str, Any] = Field(default_factory=dict)

class ReviewDecision(str, Enum):
    approve = "approve"
    correct = "correct"
    escalate = "escalate"

class ReviewRequest(BaseModel):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    comments: str = ""
    corrected_draft: KnowledgeDraft | None = None

    @field_validator("reviewer")
    @classmethod
    def named_reviewer(cls, value):
        if not value.strip():
            raise ValueError("Enter the name or role of the human reviewer")
        return value.strip()

    @model_validator(mode="after")
    def valid_correction(self):
        if self.decision == ReviewDecision.correct and self.corrected_draft is None:
            raise ValueError("A correction requires the corrected draft")
        return self

class ReviewRecord(BaseModel):
    review_id: str
    draft_id: str
    event_id: str
    decision: ReviewDecision
    reviewer: str
    comments: str = ""
    timestamp: datetime = Field(default_factory=utcnow)

class KnowledgeRecord(BaseModel):
    knowledge_id: str
    event_id: str
    draft: KnowledgeDraft
    review: ReviewRecord
    searchable_text: str
    created_at: datetime = Field(default_factory=utcnow)

class RAGQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    event_id: str | None = None

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError("Enter a question")
        return value.strip()

class UnitConversionRequest(BaseModel):
    value: float
    from_unit: str = Field(min_length=1, max_length=80)
    to_unit: str = Field(min_length=1, max_length=80)

    @field_validator("value", mode="before")
    @classmethod
    def finite_measurement(cls, value):
        import math
        if isinstance(value, bool):
            raise ValueError("Enter a numeric measurement, not a true/false value")
        try:
            converted = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Enter a finite numeric measurement") from exc
        if not math.isfinite(converted):
            raise ValueError("Enter a finite numeric measurement")
        return converted


class QualityReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectations: dict[str, Any] | None = None

class ResetDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["RESET"]

class GenerateEventRequest(BaseModel):
    domain: str
    seed: int = 42

class GenerateCustomEventRequest(BaseModel):
    generator: str
    seed: int = 42
    dataset_name: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
