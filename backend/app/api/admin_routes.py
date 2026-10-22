"""Administration: user accounts and the audit log. Admin only."""

import re
import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.routes import _get
from app.audit import audit
from app.auth.deps import actor_label, require_admin
from app.auth.passwords import hash_password
from app.auth.routes import user_out
from app.auth.service import revoke_all_sessions
from app.db import tx
from app.errors import AppError
from app.models import AppUser, AuditEvent

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
MIN_PASSWORD = 8


def _page(total: int, items: list, page: int, size: int) -> dict:
    return {"items": items, "total": total, "page": page, "size": size}


def admin_user_out(u: AppUser) -> dict:
    return user_out(u) | {
        "is_active": u.is_active,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
    }


# ---------- users ----------


@router.get("/users")
def list_users(
    q: str | None = None,
    role: str | None = Query(default=None, pattern="^(admin|member)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(tx),
) -> dict:
    stmt = select(AppUser)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(AppUser.username.ilike(like), AppUser.display_name.ilike(like)))
    if role:
        stmt = stmt.where(AppUser.role == role)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(
        stmt.order_by(AppUser.username).offset((page - 1) * size).limit(size)
    ).all()
    return _page(total or 0, [admin_user_out(u) for u in rows], page, size)


class UserIn(BaseModel):
    username: str
    display_name: str | None = None
    role: str = Field(pattern="^(admin|member)$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=1024)
    # Evidence actor this member speaks for; defaults to the username. Admins have none.
    person_id: str | None = None


def _check_person_free(session: Session, person_id: str, user_id: uuid.UUID | None) -> None:
    other = session.scalar(select(AppUser).where(AppUser.person_id == person_id))
    if other is not None and other.id != user_id:
        raise AppError(409, "person_taken", f"person '{person_id}' already has an account")


@router.post("/users", status_code=201)
def create_user(
    body: UserIn, session: Session = Depends(tx), admin: AppUser = Depends(require_admin)
) -> dict:
    username = body.username.strip().lower()
    if not USERNAME.match(username):
        raise AppError(
            422, "invalid_username", "use 2-64 lowercase letters, digits, '.', '_' or '-'"
        )
    if session.scalar(select(AppUser).where(AppUser.username == username)) is not None:
        raise AppError(409, "username_taken", f"username '{username}' is taken")
    person_id = None
    if body.role == "member":
        person_id = (body.person_id or username).strip()
        _check_person_free(session, person_id, None)
    user = AppUser(
        username=username,
        display_name=body.display_name,
        role=body.role,
        person_id=person_id,
        password_hash=hash_password(body.password),
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.refresh(user)
    audit(
        session,
        None,
        actor_label(admin),
        "user.created",
        "app_user",
        user.id,
        metadata={"username": username, "role": user.role, "person_id": person_id},
    )
    return admin_user_out(user)


class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD, max_length=1024)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserPatch,
    session: Session = Depends(tx),
    admin: AppUser = Depends(require_admin),
) -> dict:
    user = _get(session, AppUser, user_id, "user")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and changes.get("is_active") is False:
        raise AppError(422, "cannot_deactivate_self", "you cannot deactivate your own account")
    if user.id == admin.id and changes.get("role", user.role) != user.role:
        raise AppError(422, "cannot_change_own_role", "you cannot change your own role")

    changed: dict = {}
    if "display_name" in changes and body.display_name != user.display_name:
        changed["display_name"] = body.display_name
        user.display_name = body.display_name
    if body.role is not None and body.role != user.role:
        changed["role"] = body.role
        user.role = body.role
        if body.role == "member" and user.person_id is None:
            _check_person_free(session, user.username, user.id)
            user.person_id = changed["person_id"] = user.username
    revoke = False
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = changed["is_active"] = body.is_active
        revoke = not body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changed["password_reset"] = True
        revoke = True  # a reset password signs the account out everywhere
    if revoke:
        changed["sessions_revoked"] = revoke_all_sessions(session, user.id)
    if changed:
        action = "user.updated"
        if changed.get("is_active") is False:
            action = "user.deactivated"
        elif changed.get("is_active") is True:
            action = "user.reactivated"
        audit(session, None, actor_label(admin), action, "app_user", user.id, metadata=changed)
    return admin_user_out(user)


# ---------- audit log ----------


def _audit_out(e: AuditEvent) -> dict:
    return {
        "id": e.id,
        "handoff_id": str(e.handoff_id) if e.handoff_id else None,
        "actor_id": e.actor_id,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": str(e.target_id),
        "target_revision": e.target_revision,
        "metadata": e.metadata_,
        "created_at": e.created_at,
    }


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


@router.get("/audit")
def list_audit(
    actor: str | None = None,
    action: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(tx),
) -> dict:
    """Newest first. date_from and date_to are inclusive UTC calendar days."""
    stmt = select(AuditEvent)
    if actor:
        stmt = stmt.where(AuditEvent.actor_id == actor)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if date_from:
        stmt = stmt.where(AuditEvent.created_at >= _day_start(date_from))
    if date_to:
        stmt = stmt.where(AuditEvent.created_at < _day_start(date_to + timedelta(days=1)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(
        stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return _page(total or 0, [_audit_out(e) for e in rows], page, size)
