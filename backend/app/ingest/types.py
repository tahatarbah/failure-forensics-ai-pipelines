from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SpanDraft:
    id: str
    name: str
    kind: str = "unknown"
    status: str = "ok"
    parent_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    order_index: int = 0


@dataclass
class ArtifactDraft:
    id: str
    kind: str
    label: str
    content: str
    span_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    domain: str
    outcome: str
    started_at: datetime | None
    ended_at: datetime | None
    failure_span_id: str | None
    spans: list[SpanDraft]
    artifacts: list[ArtifactDraft]
    summary: str
    adapter: str
