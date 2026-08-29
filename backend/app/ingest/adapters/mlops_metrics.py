from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from app.ingest.types import ArtifactDraft, IngestResult, SpanDraft


def _load_payload(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {"metrics": data}
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return {"metrics": rows, "epochs": rows}
    data = json.loads(text)
    if isinstance(data, list):
        return {"metrics": data, "epochs": data}
    return data if isinstance(data, dict) else {"metrics": []}


def parse_mlops_metrics(path: Path) -> IngestResult:
    data = _load_payload(path)
    epochs = data.get("epochs") or data.get("metrics") or []
    baseline = data.get("baseline") or {}
    config = data.get("config") or {}
    logs = data.get("logs") or data.get("log") or ""

    spans: list[SpanDraft] = []
    artifacts: list[ArtifactDraft] = []
    failure_id: str | None = None
    base_time = datetime.utcnow() - timedelta(hours=1)

    if isinstance(epochs, list):
        for i, row in enumerate(epochs):
            if not isinstance(row, dict):
                continue
            sid = str(uuid.uuid4())
            epoch_n = row.get("epoch", i)
            loss = row.get("loss")
            status = "ok"
            attrs = dict(row)

            # Detect NaN / spike / error markers
            loss_s = str(loss).lower() if loss is not None else ""
            if loss_s in {"nan", "inf", "-inf"} or row.get("status") == "error":
                status = "error"
            if row.get("error"):
                status = "error"
                attrs["error"] = row["error"]

            name = str(row.get("name") or f"epoch-{epoch_n}")
            kind = str(row.get("kind") or ("eval" if "val" in name.lower() or row.get("split") == "val" else "train_epoch"))

            draft = SpanDraft(
                id=sid,
                name=name,
                kind=kind,
                status=status,
                started_at=base_time + timedelta(minutes=i * 5),
                ended_at=base_time + timedelta(minutes=i * 5 + 4),
                attrs=attrs,
                order_index=i,
            )
            spans.append(draft)
            artifacts.append(
                ArtifactDraft(
                    id=str(uuid.uuid4()),
                    kind="metrics",
                    label=f"Metrics · {name}",
                    content=json.dumps(row, indent=2, default=str),
                    span_id=sid,
                    meta={"epoch": epoch_n},
                )
            )
            if status == "error":
                failure_id = sid

    # Optional final deploy / checkpoint step from config/error
    if data.get("error") or data.get("exit_code") not in (None, 0, "0"):
        sid = str(uuid.uuid4())
        err = str(data.get("error") or f"Non-zero exit: {data.get('exit_code')}")
        spans.append(
            SpanDraft(
                id=sid,
                name="job-failure",
                kind="train_epoch",
                status="error",
                started_at=base_time + timedelta(minutes=len(spans) * 5),
                ended_at=base_time + timedelta(minutes=len(spans) * 5 + 1),
                attrs={"exit_code": data.get("exit_code"), "error": err},
                order_index=len(spans),
            )
        )
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="error",
                label="Job error",
                content=err,
                span_id=sid,
            )
        )
        failure_id = sid

    if logs:
        sid = spans[-1].id if spans else str(uuid.uuid4())
        if not spans:
            spans.append(
                SpanDraft(
                    id=sid,
                    name="training-log",
                    kind="train_epoch",
                    status="error" if "error" in str(logs).lower() else "ok",
                    order_index=0,
                )
            )
            if spans[0].status == "error":
                failure_id = sid
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="log",
                label="Training log",
                content=str(logs)[:50000],
                span_id=sid,
            )
        )

    if baseline:
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="metrics",
                label="Baseline metrics",
                content=json.dumps(baseline, indent=2, default=str),
                meta={"baseline": True},
            )
        )

    if config:
        artifacts.append(
            ArtifactDraft(
                id=str(uuid.uuid4()),
                kind="config",
                label="Job config",
                content=json.dumps(config, indent=2, default=str),
            )
        )

    # Metric regression vs baseline
    if baseline and spans:
        for span in spans:
            for metric_key, base_val in baseline.items():
                if metric_key in span.attrs:
                    try:
                        cur = float(span.attrs[metric_key])
                        base = float(base_val)
                        # Higher is better for accuracy/f1; lower for loss/error
                        if metric_key.lower() in {"loss", "error_rate", "rmse", "mae"}:
                            if cur > base * 1.25:
                                span.attrs["regression"] = {metric_key: {"current": cur, "baseline": base}}
                        else:
                            if cur < base * 0.9:
                                span.attrs["regression"] = {metric_key: {"current": cur, "baseline": base}}
                    except (TypeError, ValueError):
                        pass

    started = min((s.started_at for s in spans if s.started_at), default=None)
    ended = max((s.ended_at for s in spans if s.ended_at), default=None)

    return IngestResult(
        domain="mlops",
        outcome="failed" if failure_id else "succeeded",
        started_at=started,
        ended_at=ended,
        failure_span_id=failure_id,
        spans=spans,
        artifacts=artifacts,
        summary=f"Ingested MLOps metrics with {len(spans)} steps",
        adapter="mlops_metrics",
    )
