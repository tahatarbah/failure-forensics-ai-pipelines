from __future__ import annotations

import json
from typing import Any

from app.detectors.base import HypothesisDraft
from app.models import Artifact, Case, Run, Span


def _text_blob(span: Span, artifacts: list[Artifact]) -> str:
    parts = [json.dumps(span.attrs, default=str)]
    for a in artifacts:
        if a.span_id == span.id:
            parts.append(a.content)
    return "\n".join(parts).lower()


class EmptyOrTruncatedOutputDetector:
    id = "llm.empty_or_truncated_output"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        for span in spans:
            if span.kind not in {"llm"}:
                continue
            outputs = span.attrs.get("outputs") or span.attrs.get("response") or span.attrs.get("gen_ai.completion")
            text = ""
            if outputs is not None:
                text = outputs if isinstance(outputs, str) else json.dumps(outputs)
            else:
                for a in artifacts:
                    if a.span_id == span.id and a.kind == "response":
                        text = a.content
                        break
            stripped = text.strip()
            if stripped in {"", "{}", "[]", "null", '""'}:
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Empty or missing model output",
                        confidence=0.9,
                        rationale=f"Span `{span.name}` produced an empty completion.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
            elif stripped.endswith("...") or "truncated" in stripped.lower() or span.attrs.get("finish_reason") == "length":
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Truncated model output",
                        confidence=0.75,
                        rationale=f"Span `{span.name}` shows truncation signals (finish_reason/length or ellipsis).",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


class ToolSchemaFailureDetector:
    id = "llm.tool_schema_failure"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = (
            "validation error",
            "invalid tool",
            "schema",
            "jsondecodeerror",
            "function call",
            "tool_call",
            "pydantic",
        )
        for span in spans:
            if span.kind not in {"tool", "agent", "llm", "parser"} and span.status != "error":
                continue
            blob = _text_blob(span, artifacts)
            if span.status == "error" and span.kind == "tool":
                title = "Tool execution failure"
                conf = 0.85
                if any(p in blob for p in ("validation", "schema", "invalid tool", "pydantic")):
                    title = "Tool/schema validation failure"
                    conf = 0.9
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title=title,
                        confidence=conf,
                        rationale=f"Tool span `{span.name}` ended in error.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
                continue
            if any(p in blob for p in patterns) and ("error" in blob or span.status == "error"):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Tool/schema validation failure",
                        confidence=0.8,
                        rationale=f"Detected schema/tool validation language near `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


class RetrievalMissDetector:
    id = "llm.retrieval_miss"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        for span in spans:
            if span.kind not in {"retrieval", "retriever"} and "retriev" not in span.name.lower():
                continue
            attrs = span.attrs
            outputs = attrs.get("outputs") if isinstance(attrs.get("outputs"), dict) else {}
            docs = attrs.get("documents") or outputs.get("documents") or attrs.get("hits") or attrs.get("outputs")
            count = attrs.get("hit_count") or outputs.get("hit_count") or attrs.get("num_results")
            scores = attrs.get("scores") or outputs.get("scores") or attrs.get("similarities")
            miss = False
            rationale = ""
            if count == 0 or count == "0":
                miss = True
                rationale = "Retriever returned zero hits."
            elif docs in ([], None, {}, ""):
                miss = True
                rationale = "Retriever documents/outputs are empty."
            elif isinstance(docs, list) and len(docs) == 0:
                miss = True
                rationale = "Retriever returned an empty document list."
            elif isinstance(docs, dict) and not docs.get("documents") and docs.get("hit_count") in (0, "0", None):
                if "hit_count" in docs or "documents" in docs:
                    miss = True
                    rationale = "Retriever documents/outputs are empty."
            elif isinstance(scores, list) and scores and max(float(s) for s in scores) < 0.25:
                miss = True
                rationale = f"Top similarity score is very low ({max(float(s) for s in scores):.3f})."
            if miss or span.status == "error":
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Retrieval miss / weak matches",
                        confidence=0.88,
                        rationale=rationale or f"Retrieval span `{span.name}` failed to provide useful context.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


class ContextOverflowDetector:
    id = "llm.context_overflow"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = ("context length", "maximum context", "token limit", "too many tokens", "context_length_exceeded")
        for span in spans:
            blob = _text_blob(span, artifacts)
            if any(p in blob for p in patterns):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Context window overflow",
                        confidence=0.92,
                        rationale=f"Token/context limit signals found in `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


class RetryStormDetector:
    id = "llm.retry_storm"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        rate_limited = [s for s in spans if "rate" in _text_blob(s, artifacts) and "limit" in _text_blob(s, artifacts)]
        retries = [s for s in spans if s.attrs.get("retry") or s.attrs.get("attempt") or "retry" in s.name.lower()]
        if len(rate_limited) >= 2 or len(retries) >= 3:
            refs = [{"type": "span", "id": s.id} for s in (rate_limited or retries)[:5]]
            out.append(
                HypothesisDraft(
                    detector_id=self.id,
                    title="Retry storm / rate-limit loop",
                    confidence=0.78,
                    rationale=f"Observed {len(rate_limited)} rate-limit related spans and {len(retries)} retry attempts.",
                    evidence_refs=refs,
                )
            )
        return out


class GuardrailBlockDetector:
    id = "llm.guardrail_block"
    domains = {"llm_pipeline"}

    def run(self, case: Case, run: Run, spans: list[Span], artifacts: list[Artifact]) -> list[HypothesisDraft]:
        out: list[HypothesisDraft] = []
        patterns = ("content_policy", "guardrail", "blocked by policy", "safety system", "moderation", "refused")
        for span in spans:
            blob = _text_blob(span, artifacts)
            if any(p in blob for p in patterns):
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="Guardrail or policy block",
                        confidence=0.86,
                        rationale=f"Policy/guardrail block language detected in `{span.name}`.",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out


LLM_DETECTORS = [
    EmptyOrTruncatedOutputDetector(),
    ToolSchemaFailureDetector(),
    RetrievalMissDetector(),
    ContextOverflowDetector(),
    RetryStormDetector(),
    GuardrailBlockDetector(),
]
