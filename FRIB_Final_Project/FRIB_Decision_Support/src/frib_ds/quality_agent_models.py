"""Validated, proposal-only outputs from the data-quality model."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from frib_ds.ai_settings import AISelection


class QualityAgentSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = Field(default=False, strict=True)
    automatic: bool = Field(default=True, strict=True)
    selection: AISelection | None = None
    max_model_calls: int = Field(default=4, ge=1, le=6, strict=True)

    @model_validator(mode='after')
    def configured(self):
        if self.enabled and self.selection is None:
            raise ValueError('Choose and test a quality-agent model before enabling it.')
        return self


class ProposedRepair(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    action: Literal['review_only', 'replace_sample', 'exclude_samples', 'set_display_label'] = 'review_only'
    value: float | None = Field(default=None,strict=True)
    label: str | None = Field(default=None, max_length=120)
    rationale: str = Field(default='', max_length=400)


class SampleEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    index: int = Field(ge=0,strict=True)
    value: float = Field(strict=True)


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=80)
    severity: Literal['low', 'medium', 'high']
    confidence: float = Field(ge=0, le=1,strict=True)
    signal_name: str | None
    start_index: int | None = Field(ge=0, strict=True)
    end_index: int | None = Field(ge=0, strict=True)
    explanation: str = Field(min_length=1, max_length=600)
    recommended_check: str = Field(min_length=1, max_length=400)
    related_event_id: str | None = Field(default=None, max_length=120)
    evidence: list[SampleEvidence] = Field(max_length=8)
    repair: ProposedRepair = Field(default_factory=ProposedRepair)


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: Literal['signal_summary', 'read_window', 'compare_dataset']
    signal_name: str | None = Field(default=None, max_length=200)
    start_index: int = Field(default=0, ge=0, strict=True)
    count: int = Field(default=64, ge=1, le=96, strict=True)
    event_id: str | None = Field(default=None, max_length=120)


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(max_length=800)
    findings: list[AgentFinding] = Field(default_factory=list, max_length=6)
    read_requests: list[ReadRequest] = Field(default_factory=list, max_length=2)


class FindingReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['accept', 'dismiss']
    reviewer: str = Field(min_length=1, max_length=100)
    comments: str = Field(default='', max_length=2000)


class RepairApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reviewer: str = Field(min_length=1, max_length=100)
    confirmed: bool = Field(strict=True)
    proposal_hash: str = Field(min_length=64, max_length=64)


class ValidationExplanationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    errors: list[str] = Field(min_length=1,max_length=20)
    context: str = Field(default='',max_length=2000)

    @model_validator(mode='after')
    def bounded_errors(self):
        if any(len(item)>800 for item in self.errors): raise ValueError('Each error explanation input is limited to 800 characters.')
        return self


class ValidationAdvice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    explanation: str = Field(max_length=1500)
    suggested_checks: list[str] = Field(max_length=6)

    @model_validator(mode='after')
    def bounded_checks(self):
        if any(len(item)>500 for item in self.suggested_checks): raise ValueError('Validation advice exceeds its response budget.')
        return self
