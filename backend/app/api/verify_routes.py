"""Verify endpoints (docs/03 'API shape'). Reads take `viewer_id`; the role decides the view.

No authentication exists yet: viewer_id/actor_id come from the request and are only
suitable for the demo (see README).
"""

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as S
from app.api.routes import _get, tx
from app.errors import AppError
from app.models import Attempt, Exercise, KnowledgeVersion, Operation
from app.operations import run_idempotent
from app.verify import service as V
from app.verify.contract import Criterion, ExerciseDraft

router = APIRouter(prefix="/api")


def _attempts(session: Session, exercise: Exercise, viewer_role: str, viewer: str) -> list:
    stmt = select(Attempt).where(Attempt.exercise_id == exercise.id)
    if viewer_role == "successor":
        stmt = stmt.where(Attempt.successor_id == viewer)
    return list(session.scalars(stmt.order_by(Attempt.created_at)).all())


def _exercise_view(session: Session, exercise: Exercise, viewer: str) -> dict:
    version, _, handoff = V.exercise_context(session, exercise)
    r = V.role(handoff, viewer)
    if r == "successor" and exercise.status != "ready":
        raise AppError(403, "not_released", "this exercise has not been released yet")
    return S.exercise_out(exercise, version, r, _attempts(session, exercise, r, viewer))


def _attempt_view(session: Session, attempt: Attempt, viewer: str) -> dict:
    exercise = session.get(Exercise, attempt.exercise_id)
    version, _, handoff = V.exercise_context(session, exercise)
    r = V.role(handoff, viewer)
    if r == "successor" and attempt.successor_id != viewer:
        raise AppError(403, "not_owner", "this attempt belongs to someone else")
    return S.attempt_out(attempt, exercise, version, r)


class ActorIn(BaseModel):
    actor_id: str


@router.post("/knowledge/{version_id}/exercises", status_code=201)
def create_exercise(
    version_id: str,
    body: ActorIn,
    session: Session = Depends(tx),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    v = _get(session, KnowledgeVersion, version_id, "knowledge version")
    eid, _ = run_idempotent(
        session,
        "generate_exercise",
        idempotency_key,
        {"version": version_id, "actor": body.actor_id},
        None,
        "exercise",
        lambda: V.create_exercise(session, v, body.actor_id).id,
    )
    return _exercise_view(session, session.get(Exercise, eid), body.actor_id)


@router.get("/knowledge/{version_id}/exercises")
def list_exercises(
    version_id: str, viewer_id: str = Query(...), session: Session = Depends(tx)
) -> list[dict]:
    v = _get(session, KnowledgeVersion, version_id, "knowledge version")
    _, handoff = V.version_context(session, v)
    r = V.role(handoff, viewer_id)
    stmt = select(Exercise).where(Exercise.knowledge_version_id == v.id)
    if r == "successor":
        stmt = stmt.where(Exercise.status == "ready")
    rows = session.scalars(stmt.order_by(Exercise.created_at)).all()
    return [_exercise_view(session, e, viewer_id) for e in rows]


class ExerciseDraftIn(BaseModel):
    scenario: str
    criteria: list[Criterion]
    expected_revision: int
    actor_id: str


@router.put("/exercises/{exercise_id}/draft")
def put_exercise_draft(
    exercise_id: str, body: ExerciseDraftIn, session: Session = Depends(tx)
) -> dict:
    e = _get(session, Exercise, exercise_id, "exercise")
    draft = ExerciseDraft(scenario=body.scenario, criteria=body.criteria)
    V.save_exercise_draft(session, e, draft, body.expected_revision, body.actor_id)
    return _exercise_view(session, e, body.actor_id)


class ApproveIn(BaseModel):
    expected_revision: int
    actor_id: str


@router.post("/exercises/{exercise_id}/approve")
def approve_exercise(exercise_id: str, body: ApproveIn, session: Session = Depends(tx)) -> dict:
    e = _get(session, Exercise, exercise_id, "exercise")
    V.approve_exercise(session, e, body.expected_revision, body.actor_id)
    return _exercise_view(session, e, body.actor_id)


@router.get("/exercises/{exercise_id}")
def get_exercise(
    exercise_id: str, viewer_id: str = Query(...), session: Session = Depends(tx)
) -> dict:
    return _exercise_view(session, _get(session, Exercise, exercise_id, "exercise"), viewer_id)


class AttemptIn(BaseModel):
    actor_id: str
    answer: str


@router.post("/exercises/{exercise_id}/attempts", status_code=201)
def submit_attempt(
    exercise_id: str,
    body: AttemptIn,
    session: Session = Depends(tx),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    e = _get(session, Exercise, exercise_id, "exercise")
    attempt, _ = V.submit_attempt(session, e, body.answer, body.actor_id, idempotency_key)
    return _attempt_view(session, attempt, body.actor_id)


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: str, viewer_id: str = Query(...), session: Session = Depends(tx)
) -> dict:
    return _attempt_view(session, _get(session, Attempt, attempt_id, "attempt"), viewer_id)


@router.post("/attempts/{attempt_id}/reassess")
def reassess(attempt_id: str, body: ActorIn, session: Session = Depends(tx)) -> dict:
    a = _get(session, Attempt, attempt_id, "attempt")
    V.reassess_attempt(session, a, body.actor_id)
    return _attempt_view(session, a, body.actor_id)


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str, session: Session = Depends(tx)) -> dict:
    return S.operation_out(_get(session, Operation, operation_id, "operation"))
