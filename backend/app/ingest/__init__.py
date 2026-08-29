from __future__ import annotations

from pathlib import Path

from app.ingest.adapters.langchain_trace import parse_langchain_trace
from app.ingest.adapters.mlops_metrics import parse_mlops_metrics
from app.ingest.adapters.otlp_json import parse_otlp_json
from app.ingest.adapters.plain_logs import parse_plain_logs
from app.ingest.detect_format import detect_domain_from_format, sniff_format
from app.ingest.types import IngestResult


def ingest_file(path: Path, domain_override: str | None = None) -> IngestResult:
    fmt = sniff_format(path)
    if fmt == "langchain_trace":
        result = parse_langchain_trace(path)
    elif fmt == "mlops_metrics":
        result = parse_mlops_metrics(path)
    elif fmt == "plain_logs":
        result = parse_plain_logs(path)
    else:
        result = parse_otlp_json(path)

    if domain_override and domain_override != "auto":
        result.domain = domain_override
    elif result.domain == "unknown":
        result.domain = detect_domain_from_format(fmt, path)

    return result
