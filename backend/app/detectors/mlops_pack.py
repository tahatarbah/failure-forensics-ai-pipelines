from __future__ import annotations

import json
import math
import re

from app.detectors.base import HypothesisDraft
from app.models import Artifact, Case, Run, Span


def _blob(span: Span, artifacts: list[Artifact]) -> str:
    parts = [json.dumps(span.attrs, default=str)]
    for a in artifacts:
        if a.span_id == span.id or (a.span_id is None and a.kind == "log"):
            parts.append(a.content)
    return "\n".join(parts).lower()


class TracebackExitDetector:
    id = "mlops.traceback_exit"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        for span in spans:
            blob = _blob(span, artifacts)
            if "traceback" in blob or re.search(r"exit.?code[^0-9]*[1-9]", blob) or span.attrs.get("exit_code") not in (
                None,
                0,
                "0",
            ):
                if "traceback" in blob or span.status == "error" or span.attrs.get("exit_code") not in (None, 0, "0"):
                    out.append(
                        HypothesisDraft(
                            detector_id=self.id,
                            title="Non-zero exit / traceback locus",
                            confidence=0.9,
                            rationale=f"Traceback or non-zero exit associated with `{span.name}`.",
                            evidence_refs=[{"type": "span", "id": span.id}],
                        )
                    )
        # Also scan unscoped log artifacts
        for art in artifacts:
            if art.kind in {"log", "error"} and ("traceback" in art.content.lower() or "exception" in art.content.lower()):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Traceback found in job logs",
                        confidence=0.88,
                        rationale="Stack trace detected in uploaded logs.",
                        evidence_refs=[{"type": "artifact", "id": art.id}],
                    )
                )
                break
        return out


class LossDivergenceDetector:
    id = "mlops.loss_divergence"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        losses: list[tuple[Span, float]] = []
        for span in spans:
            if "loss" not in span.attrs:
                continue
            try:
                val = float(span.attrs["loss"])
            except (TypeError, ValueError):
                s = str(span.attrs["loss"]).lower()
                if s in {"nan", "inf", "-inf"}:
                    out.append(
                        HypothesisDraft(
                            detector_id=self.id,
                            title="Loss became NaN/Inf",
                            confidence=0.95,
                            rationale=f"`{span.name}` reports loss={span.attrs['loss']}.",
                            evidence_refs=[{"type": "span", "id": span.id}],
                        )
                    )
                continue
            if math.isnan(val) or math.isinf(val):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Loss became NaN/Inf",
                        confidence=0.95,
                        rationale=f"`{span.name}` reports non-finite loss.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
            else:
                losses.append((span, val))

        if len(losses) >= 2:
            prev = losses[0][1]
            for span, val in losses[1:]:
                if prev > 0 and val > prev * 3:
                    out.append(
                        HypothesisDraft(
                            detector_id=self.id,
                            title="Loss spike / divergence",
                            confidence=0.82,
                            rationale=f"Loss jumped from {prev:.4f} to {val:.4f} at `{span.name}`.",
                            evidence_refs=[{"type": "span", "id": span.id}],
                        )
                    )
                prev = val
        return out


class MetricRegressionDetector:
    id = "mlops.metric_regression"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        for span in spans:
            reg = span.attrs.get("regression")
            if isinstance(reg, dict) and reg:
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Metric regression vs baseline",
                        confidence=0.8,
                        rationale=f"`{span.name}` regressed relative to baseline: {json.dumps(reg)}.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        for art in artifacts:
            if art.meta.get("baseline"):
                # soft signal if any eval span looks worse — already handled via attrs
                pass
        return out


class ResourceOOMDetector:
    id = "mlops.resource_oom"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = ("out of memory", "oom", "cuda error", "cudnn", "killed", "memoryerror")
        for span in spans:
            blob = _blob(span, artifacts)
            if any(p in blob for p in patterns):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="OOM / CUDA / resource failure",
                        confidence=0.93,
                        rationale=f"Resource exhaustion signals in `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        for art in artifacts:
            low = art.content.lower()
            if any(p in low for p in patterns):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="OOM / CUDA / resource failure",
                        confidence=0.93,
                        rationale="Resource exhaustion language found in logs.",
                        evidence_refs=[{"type": "artifact", "id": art.id}],
                    )
                )
                break
        return out


class DataSchemaDetector:
    id = "mlops.data_schema"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = (
            "keyerror",
            "missing feature",
            "column not found",
            "schema",
            "unexpected dtype",
            "feature.*missing",
        )
        for span in spans:
            blob = _blob(span, artifacts)
            if any(re.search(p, blob) for p in patterns):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Data schema / missing-feature error",
                        confidence=0.84,
                        rationale=f"Schema/feature mismatch signals near `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


class CheckpointWriteDetector:
    id = "mlops.checkpoint_write"
    domains = {"mlops"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = ("checkpoint", "failed to save", "permission denied", "no space left", "artifact write")
        for span in spans:
            blob = _blob(span, artifacts)
            if "checkpoint" in blob and any(p in blob for p in ("fail", "error", "denied", "no space")):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Checkpoint / artifact write failure",
                        confidence=0.87,
                        rationale=f"Checkpoint/artifact write failure near `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


MLOPS_DETECTORS = [
    TracebackExitDetector(),
    LossDivergenceDetector(),
    MetricRegressionDetector(),
    ResourceOOMDetector(),
    DataSchemaDetector(),
    CheckpointWriteDetector(),
]
