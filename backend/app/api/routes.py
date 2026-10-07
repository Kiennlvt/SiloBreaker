import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.analysis.service import run_analysis
from app.api import serializers as S
from app.config import get_settings
from app.db import get_session
from app.errors import AppError
from app.evidence.importer import import_bundle
from app.knowledge import service as K
from app.knowledge.content import KnowledgeContent, structure_answer
from app.knowledge.okf import render_okf
from app.models import (
    Analysis,
    EvidenceBundle,
    EvidenceChunk,
    EvidenceItem,
    Finding,
    Handoff,
    KnowledgeVersion,
)
from app.operations import run_idempotent

router = APIRouter(prefix="/api")


def tx() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    for session in get_session():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def _get(session: Session, model, id_: str, name: str):
    try:
        row = session.get(model, uuid.UUID(id_))
    except ValueError:
        row = None
    if row is None:
        raise AppError(404, "not_found", f"{name} not found")
    return row


def _people(session: Session, bundle_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(EvidenceItem.author_id, EvidenceItem.author_display_name)
        .where(EvidenceItem.bundle_id == bundle_id, EvidenceItem.author_id.is_not(None))
        .distinct()
        .order_by(EvidenceItem.author_id)
    ).all()
    return [{"id": r[0], "display_name": r[1]} for r in rows]


# ---------- evidence ----------


@router.get("/health")
def health(session: Session = Depends(tx)) -> dict:
    session.execute(text("select 1"))
    return {"status": "ok", "ai_provider": get_settings().ai_provider}


@router.post("/bundles/import")
def import_fixture_bundle(session: Session = Depends(tx)) -> dict:
    bundle = import_bundle(session, get_settings().fixtures_input_dir)
    return _bundle(session, bundle)


@router.get("/bundles/{bundle_id}")
def get_bundle(bundle_id: str, session: Session = Depends(tx)) -> dict:
    return _bundle(session, _get(session, EvidenceBundle, bundle_id, "bundle"))


def _bundle(session: Session, bundle: EvidenceBundle) -> dict:
    count = session.scalar(select(func.count()).where(EvidenceItem.bundle_id == bundle.id))
    return S.bundle_out(bundle, _people(session, bundle.id), count)


@router.get("/evidence/{item_id}")
def get_evidence(item_id: str, session: Session = Depends(tx)) -> dict:
    return S.item_out(_get(session, EvidenceItem, item_id, "evidence item"))


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str, session: Session = Depends(tx)) -> dict:
    chunk = _get(session, EvidenceChunk, chunk_id, "chunk")
    return S.chunk_out(chunk, session.get(EvidenceItem, chunk.evidence_item_id))


# ---------- handoff + detect ----------


class HandoffIn(BaseModel):
    bundle_id: str
    expert_id: str
    successor_id: str


@router.post("/handoffs", status_code=201)
def create_handoff(body: HandoffIn, session: Session = Depends(tx)) -> dict:
    bundle = _get(session, EvidenceBundle, body.bundle_id, "bundle")
    people = {p["id"] for p in _people(session, bundle.id)}
    for role, pid in (("expert", body.expert_id), ("successor", body.successor_id)):
        if pid not in people:
            raise AppError(422, "unknown_person", f"{role} '{pid}' does not appear in the bundle")
    if body.expert_id == body.successor_id:
        raise AppError(422, "same_person", "expert and successor must differ")
    h = Handoff(
        project_key=bundle.project_key,
        bundle_id=bundle.id,
        expert_id=body.expert_id,
        successor_id=body.successor_id,
    )
    session.add(h)
    session.flush()
    return S.handoff_out(h)


@router.get("/handoffs/{handoff_id}")
def get_handoff(handoff_id: str, session: Session = Depends(tx)) -> dict:
    h = _get(session, Handoff, handoff_id, "handoff")
    analyses = session.scalars(
        select(Analysis).where(Analysis.handoff_id == h.id).order_by(Analysis.created_at.desc())
    ).all()
    return S.handoff_out(h) | {
        "analyses": [
            {
                "id": str(a.id),
                "selected_engineer_id": a.selected_engineer_id,
                "created_at": a.created_at,
            }
            for a in analyses
        ]
    }


class AnalysisIn(BaseModel):
    selected_engineer_id: str | None = None


@router.post("/handoffs/{handoff_id}/analyses", status_code=201)
def create_analysis(
    handoff_id: str,
    body: AnalysisIn,
    session: Session = Depends(tx),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    h = _get(session, Handoff, handoff_id, "handoff")
    selected = body.selected_engineer_id or h.expert_id
    analysis_id, _ = run_idempotent(
        session,
        "analyze",
        idempotency_key,
        {"handoff": handoff_id, "selected": selected},
        h.id,
        "analysis",
        lambda: run_analysis(session, h, selected).id,
    )
    return _analysis(session, analysis_id)


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, session: Session = Depends(tx)) -> dict:
    return _analysis(session, _get(session, Analysis, analysis_id, "analysis").id)


def _analysis(session: Session, analysis_id: uuid.UUID) -> dict:
    a = session.get(Analysis, analysis_id)
    findings = session.scalars(select(Finding).where(Finding.analysis_id == analysis_id)).all()
    return S.analysis_out(a, list(findings))


# ---------- capture ----------


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str, session: Session = Depends(tx)) -> dict:
    f = _get(session, Finding, finding_id, "finding")
    versions = session.scalars(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.finding_id == f.id)
        .order_by(KnowledgeVersion.version_no)
    ).all()
    analysis = session.get(Analysis, f.analysis_id)
    handoff = session.get(Handoff, analysis.handoff_id)
    return S.finding_out(f) | {
        "handoff": S.handoff_out(handoff),
        "draft": S.draft_out(K.get_draft(session, f.id)),
        "versions": [S.version_out(v) for v in versions],
    }


class ReviewIn(BaseModel):
    action: str
    reason: str = ""
    expected_revision: int
    actor_id: str
    corrected_summary: str | None = None


@router.post("/findings/{finding_id}/review")
def review(finding_id: str, body: ReviewIn, session: Session = Depends(tx)) -> dict:
    f = _get(session, Finding, finding_id, "finding")
    f = K.review_finding(
        session,
        f.id,
        body.action,
        body.reason,
        body.expected_revision,
        body.actor_id,
        body.corrected_summary,
    )
    return S.finding_out(f)


class StructureIn(BaseModel):
    answer: str
    applicability: str | None = None


@router.post("/findings/{finding_id}/structure")
def structure(finding_id: str, body: StructureIn, session: Session = Depends(tx)) -> dict:
    """Suggests a structured draft from the expert's words. Nothing is saved."""
    f = _get(session, Finding, finding_id, "finding")
    if not body.answer.strip():
        raise AppError(422, "empty_answer", "the expert answer is empty")
    applicability = body.applicability or f"{f.title} in this project"
    return structure_answer(body.answer, applicability).model_dump()


class DraftIn(BaseModel):
    content: KnowledgeContent
    expected_revision: int | None = None
    author_id: str


@router.put("/findings/{finding_id}/draft")
def put_draft(finding_id: str, body: DraftIn, session: Session = Depends(tx)) -> dict:
    f = _get(session, Finding, finding_id, "finding")
    return S.draft_out(
        K.save_draft(session, f.id, body.content, body.expected_revision, body.author_id)
    )


class PublishIn(BaseModel):
    expected_finding_revision: int
    draft_revision: int
    approver_id: str


@router.post("/findings/{finding_id}/publish", status_code=201)
def publish(
    finding_id: str,
    body: PublishIn,
    session: Session = Depends(tx),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    f = _get(session, Finding, finding_id, "finding")
    vid, _ = run_idempotent(
        session,
        "publish",
        idempotency_key,
        {"finding": finding_id, **body.model_dump()},
        None,
        "knowledge_version",
        lambda: (
            K.publish(
                session, f.id, body.expected_finding_revision, body.draft_revision, body.approver_id
            ).id
        ),
    )
    return S.version_out(session.get(KnowledgeVersion, vid))


@router.get("/knowledge/{version_id}")
def get_version(version_id: str, session: Session = Depends(tx)) -> dict:
    return S.version_out(_get(session, KnowledgeVersion, version_id, "knowledge version"))


@router.get("/knowledge/{version_id}/okf", response_class=PlainTextResponse)
def get_okf(version_id: str, session: Session = Depends(tx)) -> PlainTextResponse:
    v = _get(session, KnowledgeVersion, version_id, "knowledge version")
    f = session.get(Finding, v.finding_id)
    analysis = session.get(Analysis, f.analysis_id)
    handoff = session.get(Handoff, analysis.handoff_id)
    titles = dict(
        session.execute(
            select(EvidenceItem.external_id, EvidenceItem.title).where(
                EvidenceItem.bundle_id == handoff.bundle_id
            )
        ).all()
    )
    md = render_okf(v, f, handoff.project_key, {k: t for k, t in titles.items() if t})
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{f.area_key}-v{v.version_no}.md"'},
    )


# ---------- demo ----------


@router.post("/demo/reset")
def reset_demo(session: Session = Depends(tx)) -> dict:
    """Clears all workflow and evidence state, then re-imports the fixture bundle (FR-24).

    TRUNCATE is used because the immutability triggers block row-level DELETE.
    """
    session.execute(
        text(
            "truncate audit_event, operation, attempt, exercise, knowledge_version, "
            "knowledge_draft, finding, analysis, handoff, evidence_chunk, evidence_item, "
            "evidence_bundle restart identity cascade"
        )
    )
    bundle = import_bundle(session, get_settings().fixtures_input_dir)
    return _bundle(session, bundle)
