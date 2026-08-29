from __future__ import annotations

from app.detectors.base import HypothesisDraft
from app.detectors.llm_pack import LLM_DETECTORS
from app.detectors.mlops_pack import MLOPS_DETECTORS
from app.models import Artifact, Case, Run, Span

ALL_DETECTORS = [*LLM_DETECTORS, *MLOPS_DETECTORS]


def run_detectors(case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
    drafts: list[HypothesisDraft] = []
    for det in ALL_DETECTORS:
        if case.domain != "unknown" and case.domain not in det.domains:
            continue
        try:
            drafts.extend(det.run(case, run, spans, artifacts))
        except Exception as exc:  # noqa: BLE001
            drafts.append(
                HypothesisDraft(
                    detector_id=getattr(det, "id", "unknown"),
                    title="Detector error",
                    confidence=0.1,
                    rationale=f"Detector failed: {exc}",
                    evidence_refs=[],
                )
            )

    seen: set[str] = set()
    unique: list[HypothesisDraft] = []
    for d in drafts:
        key = f"{d.detector_id}:{d.title}:{d.evidence_refs}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)

    unique.sort(key=lambda h: h.confidence, reverse=True)
    return unique
