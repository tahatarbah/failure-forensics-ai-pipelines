from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from app.ingest.types import ArtifactDraft, IngestResult, SpanDraft

STEP_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\s*"
    r"(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)?\s*[-:]?\s*(?P<msg>.*)$",
    re.IGNORECASE,
)

ERROR_HINTS = (
    "traceback",
    "exception",
    "error",
    "failed",
    "oom",
    "cuda",
    "out of memory",
    "rate limit",
    "timeout",
)


def _parse_line_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def parse_plain_logs(path: Path) -> IngestResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    spans: list[SpanDraft] = []
    artifacts: list[ArtifactDraft] = []
    failure_id: str | None = None

    # Group into steps by blank lines or step markers
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^(===+|---+|\[step|\*\*\*)", line.strip(), re.IGNORECASE) and current:
            chunks.append(current)
            current = [line]
        elif not line.strip() and current and len(current) > 3:
            chunks.append(current)
            current = []
        else:
            current.append(line)
    if current:
        chunks.append(current)

    if not chunks:
        chunks = [lines] if lines else [["(empty log)"]]

    for i, chunk in enumerate(chunks):
        joined = "\n".join(chunk)
        lower = joined.lower()
        first = chunk[0] if chunk else f"step-{i}"
        m = STEP_RE.match(first.strip())
        name = (m.group("msg") if m and m.group("msg") else first.strip())[:120] or f"log-step-{i}"
        ts = _parse_line_ts(m.group("ts") if m else None)
        is_error = any(h in lower for h in ERROR_HINTS)
        status = "error" if is_error else "ok"

        kind = "unknown"
        if any(k in lower for k in ("epoch", "loss", "checkpoint", "cuda", "torch")):
            kind = "train_epoch"
        elif any(k in lower for k in ("prompt", "completion", "llm", "retriev", "tool")):
            kind = "llm"
        elif "deploy" in lower:
            kind = "deploy"
        elif "eval" in lower:
            kind = "eval"

        sid = str(uuid.uuid4())
        spans.append(
            SpanDraft(
                id=sid,
                name=name[:200],
                kind=kind,
                status=status,
                started_at=ts,
                ended_at=ts,
                attrs={"line_start": i, "line_count": len(chunk)},
                order_index=i,
            )
        )
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="log",
                label=f"Log chunk {i + 1}",
                content=joined[:20000],
                span_id=sid,
            )
        )
        if is_error:
            failure_id = sid

    domain = "mlops"
    blob = text.lower()
    llm_score = sum(1 for k in ("prompt", "langchain", "retriev", "tool_call", "openai") if k in blob)
    ml_score = sum(1 for k in ("epoch", "cuda", "checkpoint", "torch", "loss=") if k in blob)
    if llm_score > ml_score:
        domain = "llm_pipeline"

    started = min((s.started_at for s in spans if s.started_at), default=None)
    ended = max((s.ended_at for s in spans if s.ended_at), default=None)

    return IngestResult(
        domain=domain,
        outcome="failed" if failure_id else "succeeded",
        started_at=started,
        ended_at=ended,
        failure_span_id=failure_id,
        spans=spans,
        artifacts=artifacts,
        summary=f"Parsed plain logs into {len(spans)} steps",
        adapter="plain_logs",
    )
