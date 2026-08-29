from __future__ import annotations

import json

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Case, Hypothesis, Run, Span


def build_explain_prompt(case: Case, run: Run | None, spans: list[Span], hyps: list[Hypothesis]) -> str:
    timeline = [
        {
            "name": s.name,
            "kind": s.kind,
            "status": s.status,
            "is_failure": bool(run and s.id == run.failure_span_id),
        }
        for s in spans[:40]
    ]
    hypotheses = [
        {"title": h.title, "confidence": h.confidence, "rationale": h.rationale, "detector": h.detector_id}
        for h in hyps[:8]
    ]
    return (
        "You are a failure forensics analyst for AI pipelines. "
        "Write a concise root-cause narrative (3-6 sentences) grounded only in the evidence. "
        "Do not invent spans or metrics.\n\n"
        f"Case: {case.title}\nDomain: {case.domain}\nSummary: {case.summary}\n"
        f"Timeline: {json.dumps(timeline)}\n"
        f"Hypotheses: {json.dumps(hypotheses)}\n"
    )


async def explain_case(db: Session, case_id: str) -> tuple[str, str]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")
    run = db.query(Run).filter(Run.case_id == case.id).first()
    spans = []
    if run:
        spans = db.query(Span).filter(Span.run_id == run.id).order_by(Span.order_index).all()
    hyps = db.query(Hypothesis).filter(Hypothesis.case_id == case.id).order_by(Hypothesis.rank).all()

    prompt = build_explain_prompt(case, run, spans, hyps)
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": "You are a precise AI pipeline failure analyst."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        narrative = data["choices"][0]["message"]["content"].strip()

    case.narrative = narrative
    db.commit()
    return narrative, "openai"
