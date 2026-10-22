"""Idempotency for mutations that create resources (docs/03 'Mutation rules').

Same key + same body -> the earlier result. Same key + different body -> 409.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.evidence.contract import sha256_json
from app.models import Operation


def run_idempotent(
    session: Session,
    kind: str,
    key: str | None,
    body: dict,
    handoff_id: uuid.UUID | None,
    result_type: str,
    action: Callable[[], uuid.UUID],
) -> tuple[uuid.UUID, bool]:
    """Returns (result_id, replayed)."""
    if not key:
        return action(), False
    request_hash = sha256_json(body)
    existing = session.scalar(
        select(Operation).where(Operation.kind == kind, Operation.idempotency_key == key)
    )
    if existing:
        if existing.request_hash != request_hash:
            raise AppError(
                409,
                "idempotency_key_reused",
                "this Idempotency-Key was used with a different request",
            )
        if existing.state == "succeeded" and existing.result_id:
            return existing.result_id, True
        raise AppError(409, "operation_in_progress", f"operation is {existing.state}")
    op = Operation(
        handoff_id=handoff_id,
        kind=kind,
        idempotency_key=key,
        request_hash=request_hash,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(op)
    try:
        session.flush()
    except IntegrityError as exc:  # concurrent request with the same key
        raise AppError(409, "operation_in_progress", "a request with this key is running") from exc
    # If the action raises, the request transaction rolls back and the key is not consumed.
    result_id = action()
    op.state = "succeeded"
    op.result_type = result_type
    op.result_id = result_id
    op.finished_at = datetime.now(UTC)
    session.flush()
    return result_id, False
