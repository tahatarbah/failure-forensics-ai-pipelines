from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models import Artifact, Case, Run, Span


@dataclass
class HypothesisDraft:
    detector_id: str
    title: str
    confidence: float
    rationale: str
    evidence_refs: list[Any] = field(default_factory=list)


class Detector(Protocol):
    id: str
    domains: set[str]

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        ...
