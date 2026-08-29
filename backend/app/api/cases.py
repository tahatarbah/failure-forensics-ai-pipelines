from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Artifact, Case, Hypothesis, Run, Span
from app.schemas import (
    ArtifactOut,
    CaseDetail,
    CaseSummary,
    ExplainResponse,
    HypothesisOut,
    RunOut,
    SpanOut,
)
from app.services.analyze import analyze_case, create_case_from_sample, create_case_from_upload
from app.services.explain import explain_case

router = APIRouter(prefix="/api")


def _case_summary(case: Case, db: Session) -> CaseSummary:
    top = (
        db.query(Hypothesis)
        .filter(Hypothesis.case_id == case.id)
        .order_by(Hypothesis.rank)
        .first()
    )
    return CaseSummary(
        id=case.id,
        title=case.title,
        domain=case.domain,
        status=case.status,
        summary=case.summary,
        created_at=case.created_at,
        top_hypothesis=top.title if top else None,
        top_confidence=top.confidence if top else None,
    )


def _case_detail(case: Case, db: Session) -> CaseDetail:
    run = db.query(Run).filter(Run.case_id == case.id).first()
    timeline: list[SpanOut] = []
    artifacts: list[ArtifactOut] = []
    if run:
        spans = db.query(Span).filter(Span.run_id == run.id).order_by(Span.order_index).all()
        timeline = [
            SpanOut(
                id=s.id,
                parent_id=s.parent_id,
                name=s.name,
                kind=s.kind,
                status=s.status,
                started_at=s.started_at,
                ended_at=s.ended_at,
                attrs=s.attrs or {},
                order_index=s.order_index,
                is_failure_locus=s.id == run.failure_span_id,
            )
            for s in spans
        ]
        arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        artifacts = [ArtifactOut.model_validate(a) for a in arts]

    hyps = db.query(Hypothesis).filter(Hypothesis.case_id == case.id).order_by(Hypothesis.rank).all()
    return CaseDetail(
        id=case.id,
        title=case.title,
        domain=case.domain,
        status=case.status,
        summary=case.summary,
        narrative=case.narrative,
        created_at=case.created_at,
        run=RunOut.model_validate(run) if run else None,
        timeline=timeline,
        hypotheses=[HypothesisOut.model_validate(h) for h in hyps],
        artifacts=artifacts,
        explain_available=bool(settings.openai_api_key),
    )


@router.get("/health")
def health():
    return {"ok": True, "service": settings.app_name}


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(db: Session = Depends(get_db)):
    cases = db.query(Case).order_by(Case.created_at.desc()).all()
    return [_case_summary(c, db) for c in cases]


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return _case_detail(case, db)


@router.get("/cases/{case_id}/timeline", response_model=list[SpanOut])
def get_timeline(case_id: str, db: Session = Depends(get_db)):
    detail = get_case(case_id, db)
    return detail.timeline


@router.get("/cases/{case_id}/hypotheses", response_model=list[HypothesisOut])
def get_hypotheses(case_id: str, db: Session = Depends(get_db)):
    detail = get_case(case_id, db)
    return detail.hypotheses


@router.post("/cases", response_model=CaseDetail)
async def create_case(
    title: str = Form("Untitled case"),
    domain: str = Form("auto"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        case = create_case_from_upload(db, title, domain, tmp_path, file.filename or "upload.bin")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Ingest failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return _case_detail(case, db)


@router.post("/cases/demo/{sample_key}", response_model=CaseDetail)
def create_demo_case(sample_key: str, db: Session = Depends(get_db)):
    try:
        case = create_case_from_sample(db, sample_key)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _case_detail(case, db)


@router.post("/cases/{case_id}/analyze", response_model=CaseDetail)
def reanalyze(case_id: str, db: Session = Depends(get_db)):
    try:
        case = analyze_case(db, case_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _case_detail(case, db)


@router.post("/cases/{case_id}/explain", response_model=ExplainResponse)
async def explain(case_id: str, db: Session = Depends(get_db)):
    try:
        narrative, source = await explain_case(db, case_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"LLM provider error: {exc}") from exc
    return ExplainResponse(narrative=narrative, source=source)
