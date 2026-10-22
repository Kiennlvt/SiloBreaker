import uuid

from sqlalchemy.orm import Session

from app.models import AuditEvent


def audit(
    session: Session,
    handoff_id: uuid.UUID | None,
    actor: str,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    revision: int | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            handoff_id=handoff_id,
            actor_id=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_revision=revision,
            metadata_=metadata or {},
        )
    )
