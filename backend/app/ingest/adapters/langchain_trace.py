from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ingest.types import ArtifactDraft, IngestResult, SpanDraft


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _walk_runs(
    node: dict[str, Any], parent_id: str | None, order: list[int]
) -> tuple[list[SpanDraft], list[ArtifactDraft], str | None]:
    spans: list[SpanDraft] = []
    artifacts: list[ArtifactDraft] = []
    failure_id: str | None = None

    sid = str(node.get("id") or uuid.uuid4())
    name = str(node.get("name") or node.get("id") or "run")
    run_type = str(node.get("run_type") or node.get("type") or "chain").lower()
    kind_map = {
        "llm": "llm",
        "chat_model": "llm",
        "retriever": "retrieval",
        "retrieval": "retrieval",
        "tool": "tool",
        "chain": "chain",
        "agent": "agent",
        "embedding": "embedding",
        "parser": "parser",
    }
    kind = kind_map.get(run_type, run_type if run_type else "chain")

    error = node.get("error")
    status = "error" if error else "ok"
    if str(node.get("status") or "").lower() in {"error", "failed"}:
        status = "error"

    attrs: dict[str, Any] = {"run_type": run_type}
    if node.get("inputs") is not None:
        attrs["inputs"] = node["inputs"]
    if node.get("outputs") is not None:
        attrs["outputs"] = node["outputs"]
    if error:
        attrs["error"] = error

    draft = SpanDraft(
        id=sid,
        name=name,
        kind=kind,
        status=status,
        parent_id=parent_id,
        started_at=_parse_ts(node.get("start_time") or node.get("started_at")),
        ended_at=_parse_ts(node.get("end_time") or node.get("ended_at")),
        attrs=attrs,
        order_index=order[0],
    )
    order[0] += 1
    spans.append(draft)
    if status == "error":
        failure_id = sid

    if node.get("inputs") is not None:
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="prompt",
                label=f"{name} · inputs",
                content=json.dumps(node["inputs"], indent=2, default=str),
                span_id=sid,
            )
        )
    if node.get("outputs") is not None:
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="response",
                label=f"{name} · outputs",
                content=json.dumps(node["outputs"], indent=2, default=str),
                span_id=sid,
            )
        )
    if error:
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="error",
                label=f"{name} · error",
                content=str(error),
                span_id=sid,
            )
        )

    children = node.get("child_runs") or node.get("children") or []
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                cs, ca, cf = _walk_runs(child, sid, order)
                spans.extend(cs)
                artifacts.extend(ca)
                if cf:
                    failure_id = cf

    return spans, artifacts, failure_id


def parse_langchain_trace(path: Path) -> IngestResult:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, list):
        roots = data
    elif isinstance(data, dict):
        if "runs" in data and isinstance(data["runs"], list):
            roots = data["runs"]
        else:
            roots = [data]
    else:
        roots = []

    all_spans: list[SpanDraft] = []
    all_artifacts: list[ArtifactDraft] = []
    failure_id: str | None = None
    order = [0]

    for root in roots:
        spans, arts, fid = _walk_runs(root, None, order)
        all_spans.extend(spans)
        all_artifacts.extend(arts)
        if fid:
            failure_id = fid

    started = min((s.started_at for s in all_spans if s.started_at), default=None)
    ended = max((s.ended_at for s in all_spans if s.ended_at), default=None)

    return IngestResult(
        domain="llm_pipeline",
        outcome="failed" if failure_id else "succeeded",
        started_at=started,
        ended_at=ended,
        failure_span_id=failure_id,
        spans=all_spans,
        artifacts=all_artifacts,
        summary=f"Ingested LangChain/LangSmith-style trace with {len(all_spans)} runs",
        adapter="langchain_trace",
    )
