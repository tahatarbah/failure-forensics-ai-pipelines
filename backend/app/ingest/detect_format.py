from __future__ import annotations

import json
from pathlib import Path


def sniff_format(path: Path, text: str | None = None) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()

    if suffix in {".log", ".txt"}:
        return "plain_logs"
    if suffix in {".csv"}:
        return "mlops_metrics"
    if suffix in {".yaml", ".yml"} and "metric" in name:
        return "mlops_metrics"
    if suffix not in {".json", ".jsonl"}:
        if suffix in {".yaml", ".yml"}:
            return "mlops_metrics"
        return "plain_logs"

    raw = text if text is not None else path.read_text(encoding="utf-8", errors="replace")
    stripped = raw.strip()
    if not stripped:
        return "plain_logs"

    # JSONL: first non-empty line is an object
    if suffix == ".jsonl" or "\n{" in stripped[:500]:
        first = next((ln for ln in stripped.splitlines() if ln.strip()), "")
        try:
            obj = json.loads(first)
            if isinstance(obj, dict) and ("spans" in obj or "name" in obj or "events" in obj):
                return "otlp_json"
        except json.JSONDecodeError:
            pass

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return "plain_logs"

    if isinstance(data, dict):
        keys = set(data.keys())
        if "runs" in keys or "child_runs" in keys or data.get("run_type") or "inputs" in keys and "outputs" in keys:
            return "langchain_trace"
        if "spans" in keys or "resourceSpans" in keys:
            return "otlp_json"
        if "epochs" in keys or "metrics" in keys or "baseline" in keys:
            return "mlops_metrics"
        if "messages" in keys or "trace" in keys:
            return "langchain_trace"
    if isinstance(data, list) and data:
        sample = data[0]
        if isinstance(sample, dict):
            if "span_id" in sample or "traceId" in sample or "name" in sample and "attributes" in sample:
                return "otlp_json"
            if "run_type" in sample or "child_runs" in sample:
                return "langchain_trace"
            if "epoch" in sample or "loss" in sample:
                return "mlops_metrics"

    return "otlp_json"


def detect_domain_from_format(fmt: str, path: Path | None = None) -> str:
    if fmt in {"langchain_trace"}:
        return "llm_pipeline"
    if fmt in {"mlops_metrics"}:
        return "mlops"
    if fmt == "plain_logs" and path:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        mlops_signals = ("cuda", "oom", "epoch", "loss=", "traceback", "torch", "tensorflow")
        llm_signals = ("prompt", "completion", "tool_call", "retrieval", "embedding", "langchain")
        ml = sum(1 for s in mlops_signals if s in text)
        ll = sum(1 for s in llm_signals if s in text)
        if ml > ll:
            return "mlops"
        if ll > ml:
            return "llm_pipeline"
    if fmt == "otlp_json" and path:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if any(k in text for k in ("retrieval", "llm", "tool", "prompt")):
            return "llm_pipeline"
        if any(k in text for k in ("train", "epoch", "deploy", "checkpoint")):
            return "mlops"
    return "unknown"
