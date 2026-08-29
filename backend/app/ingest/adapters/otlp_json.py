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
    if isinstance(value, (int, float)):
        # ns or ms heuristics
        v = float(value)
        if v > 1e14:
            v /= 1e9
        elif v > 1e11:
            v /= 1e3
        return datetime.utcfromtimestamp(v)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _attrs_from_otlp(attrs: Any) -> dict[str, Any]:
    if isinstance(attrs, dict):
        return attrs
    out: dict[str, Any] = {}
    if isinstance(attrs, list):
        for item in attrs:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            val = item.get("value", {})
            if isinstance(val, dict):
                for vk in ("stringValue", "intValue", "doubleValue", "boolValue"):
                    if vk in val:
                        out[key] = val[vk]
                        break
            else:
                out[key] = val
    return out


def parse_otlp_json(path: Path) -> IngestResult:
    raw = path.read_text(encoding="utf-8", errors="replace")
    spans_raw: list[dict[str, Any]] = []

    if path.suffix.lower() == ".jsonl":
        for line in raw.splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if "spans" in obj and isinstance(obj["spans"], list):
                spans_raw.extend(obj["spans"])
            else:
                spans_raw.append(obj)
    else:
        data = json.loads(raw)
        if isinstance(data, list):
            spans_raw = data
        elif isinstance(data, dict):
            if "spans" in data:
                spans_raw = data["spans"]
            elif "resourceSpans" in data:
                for rs in data["resourceSpans"]:
                    for ss in rs.get("scopeSpans", []):
                        spans_raw.extend(ss.get("spans", []))
            else:
                spans_raw = [data]

    drafts: list[SpanDraft] = []
    artifacts: list[ArtifactDraft] = []
    failure_id: str | None = None
    domain_hint = "unknown"

    for i, s in enumerate(spans_raw):
        sid = str(s.get("span_id") or s.get("spanId") or s.get("id") or uuid.uuid4())
        name = str(s.get("name") or s.get("operation") or f"span-{i}")
        kind = str(s.get("kind") or s.get("span_kind") or s.get("attributes", {}).get("kind") or "unknown")
        if isinstance(s.get("attributes"), dict) and "gen_ai.operation.name" in s["attributes"]:
            kind = str(s["attributes"]["gen_ai.operation.name"])
        attrs = _attrs_from_otlp(s.get("attributes") or s.get("attrs") or {})
        status_raw = s.get("status") or attrs.get("status") or "ok"
        if isinstance(status_raw, dict):
            code = status_raw.get("code") or status_raw.get("status_code") or "OK"
            status = "error" if str(code).upper() in {"ERROR", "STATUS_CODE_ERROR", "2"} else "ok"
            if status_raw.get("message"):
                attrs["status_message"] = status_raw["message"]
        else:
            status = "error" if str(status_raw).lower() in {"error", "failed", "failure"} else "ok"

        kind_l = kind.lower()
        for key, mapped in (
            ("retriev", "retrieval"),
            ("llm", "llm"),
            ("chat", "llm"),
            ("tool", "tool"),
            ("embed", "embedding"),
            ("train", "train_epoch"),
            ("eval", "eval"),
            ("deploy", "deploy"),
        ):
            if key in kind_l or key in name.lower():
                kind = mapped
                break

        if kind in {"llm", "retrieval", "tool", "embedding"}:
            domain_hint = "llm_pipeline"
        if kind in {"train_epoch", "eval", "deploy"}:
            domain_hint = "mlops"

        parent = s.get("parent_id") or s.get("parentSpanId") or s.get("parent_span_id")
        draft = SpanDraft(
            id=sid,
            name=name,
            kind=kind,
            status=status,
            parent_id=str(parent) if parent else None,
            started_at=_parse_ts(s.get("start_time") or s.get("startTimeUnixNano") or s.get("started_at")),
            ended_at=_parse_ts(s.get("end_time") or s.get("endTimeUnixNano") or s.get("ended_at")),
            attrs=attrs,
            order_index=i,
        )
        drafts.append(draft)
        if status == "error":
            failure_id = sid

        # Capture prompt/response style attrs as artifacts
        for label, keys in (
            ("prompt", ("prompt", "input", "gen_ai.prompt")),
            ("response", ("response", "output", "gen_ai.completion")),
            ("error", ("error", "exception.message", "status_message")),
        ):
            for k in keys:
                if k in attrs and attrs[k]:
                    artifacts.append(
                        ArtifactDraft(
                            id=str(uuid.uuid4()),
                            kind=label,
                            label=f"{name} · {label}",
                            content=str(attrs[k]),
                            span_id=sid,
                            meta={"attr_key": k},
                        )
                    )
                    break

    if not failure_id and drafts:
        # last span as soft failure locus if outcome unknown
        for d in reversed(drafts):
            if d.status == "error":
                failure_id = d.id
                break

    started = min((d.started_at for d in drafts if d.started_at), default=None)
    ended = max((d.ended_at for d in drafts if d.ended_at), default=None)
    outcome = "failed" if failure_id else "succeeded"
    if failure_id is None and any(d.status == "error" for d in drafts):
        outcome = "failed"

    return IngestResult(
        domain=domain_hint if domain_hint != "unknown" else "llm_pipeline",
        outcome=outcome,
        started_at=started,
        ended_at=ended,
        failure_span_id=failure_id,
        spans=drafts,
        artifacts=artifacts,
        summary=f"Ingested {len(drafts)} spans via OTLP/generic JSON",
        adapter="otlp_json",
    )
