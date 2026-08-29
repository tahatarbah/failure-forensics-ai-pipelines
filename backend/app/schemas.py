from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArtifactOut(BaseModel):
    id: str
    span_id: str | None = None
    kind: str
    label: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class SpanOut(BaseModel):
    id: str
    parent_id: str | None = None
    name: str
    kind: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    order_index: int = 0
    is_failure_locus: bool = False

    class Config:
        from_attributes = True


class HypothesisOut(BaseModel):
    id: str
    detector_id: str
    title: str
    confidence: float
    rationale: str
    evidence_refs: list[Any] = Field(default_factory=list)
    rank: int = 0

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    outcome: str
    failure_span_id: str | None = None

    class Config:
        from_attributes = True


class CaseSummary(BaseModel):
    id: str
    title: str
    domain: str
    status: str
    summary: str | None = None
    created_at: datetime
    top_hypothesis: str | None = None
    top_confidence: float | None = None

    class Config:
        from_attributes = True


class CaseDetail(BaseModel):
    id: str
    title: str
    domain: str
    status: str
    summary: str | None = None
    narrative: str | None = None
    created_at: datetime
    run: RunOut | None = None
    timeline: list[SpanOut] = Field(default_factory=list)
    hypotheses: list[HypothesisOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    explain_available: bool = False

    class Config:
        from_attributes = True


class ExplainResponse(BaseModel):
    narrative: str
    source: str
