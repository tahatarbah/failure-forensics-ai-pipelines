from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.detectors import run_detectors
from app.ingest import ingest_file
from app.models import Artifact, Case, Hypothesis, Run, Span


def persist_ingest(db: Session, case: Case, result, bundle_path: str) -> Run:
    run = Run(
        id=str(uuid.uuid4()),
        case_id=case.id,
        started_at=result.started_at,
        ended_at=result.ended_at,
        outcome=result.outcome,
        raw_bundle_path=bundle_path,
        failure_span_id=None,
    )
    db.add(run)
    db.flush()

    # Remap source span IDs so repeated demo uploads never collide globally
    id_map: dict[str, str] = {s.id: str(uuid.uuid4()) for s in result.spans}
    failure_span_id = id_map.get(result.failure_span_id) if result.failure_span_id else None
    run.failure_span_id = failure_span_id

    for s in result.spans:
        db.add(
            Span(
                id=id_map[s.id],
                run_id=run.id,
                parent_id=id_map.get(s.parent_id) if s.parent_id else None,
                name=s.name,
                kind=s.kind,
                status=s.status,
                started_at=s.started_at,
                ended_at=s.ended_at,
                attrs=s.attrs or {},
                order_index=s.order_index,
            )
        )

    for a in result.artifacts:
        db.add(
            Artifact(
                id=str(uuid.uuid4()),
                run_id=run.id,
                span_id=id_map.get(a.span_id) if a.span_id else None,
                kind=a.kind,
                label=a.label,
                content=a.content,
                meta=a.meta or {},
            )
        )

    case.domain = result.domain
    case.summary = result.summary
    case.status = "ingested"
    db.flush()
    return run


def analyze_case(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")
    run = db.query(Run).filter(Run.case_id == case.id).order_by(Run.id).first()
    if not run:
        raise ValueError("Case has no run")

    spans = db.query(Span).filter(Span.run_id == run.id).order_by(Span.order_index).all()
    artifacts = db.query(Artifact).filter(Artifact.run_id == run.id).all()

    # Clear prior hypotheses
    db.query(Hypothesis).filter(Hypothesis.case_id == case.id).delete()
    drafts = run_detectors(case, run, spans, artifacts)
    for i, d in enumerate(drafts):
        db.add(
            Hypothesis(
                id=str(uuid.uuid4()),
                case_id=case.id,
                detector_id=d.detector_id,
                title=d.title,
                confidence=d.confidence,
                rationale=d.rationale,
                evidence_refs=d.evidence_refs,
                rank=i + 1,
            )
        )

    if not run.failure_span_id:
        err = next((s for s in spans if s.status == "error"), None)
        if err:
            run.failure_span_id = err.id

    case.status = "analyzed"
    if drafts:
        case.summary = f"{drafts[0].title} (confidence {drafts[0].confidence:.0%})"
    db.commit()
    db.refresh(case)
    return case


def create_case_from_upload(
    db: Session,
    title: str,
    domain: str,
    upload_path: Path,
    original_name: str,
) -> Case:
    case_id = str(uuid.uuid4())
    dest_dir = settings.uploads_dir / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / original_name
    shutil.copy2(upload_path, dest)

    case = Case(
        id=case_id,
        title=title or original_name,
        domain=domain if domain != "auto" else "unknown",
        status="created",
    )
    db.add(case)
    db.flush()

    result = ingest_file(dest, domain_override=None if domain == "auto" else domain)
    persist_ingest(db, case, result, str(dest))
    db.commit()
    analyze_case(db, case.id)
    return db.get(Case, case.id)


def create_case_from_sample(db: Session, sample_key: str) -> Case:
    candidates = [
        Path(settings.samples_dir),
        Path(__file__).resolve().parents[3] / "samples",
        Path("/samples"),
    ]
    samples_root = next((p for p in candidates if p.exists()), candidates[0])
    mapping = {
        "rag_failure": samples_root / "rag_failure" / "trace.json",
        "agent_failure": samples_root / "agent_failure" / "trace.json",
        "training_failure": samples_root / "training_failure" / "metrics.json",
    }
    if sample_key not in mapping:
        raise ValueError(f"Unknown sample: {sample_key}")
    path = mapping[sample_key]
    if not path.exists():
        raise FileNotFoundError(f"Sample not found: {path}")

    titles = {
        "rag_failure": "Demo - RAG retrieval miss",
        "agent_failure": "Demo - Agent tool schema failure",
        "training_failure": "Demo - Training loss divergence",
    }
    domains = {
        "rag_failure": "llm_pipeline",
        "agent_failure": "llm_pipeline",
        "training_failure": "mlops",
    }
    return create_case_from_upload(db, titles[sample_key], domains[sample_key], path, path.name)
