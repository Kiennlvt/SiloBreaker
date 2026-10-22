"""Login, logout and session lookup. The cookie carries a random token; the database only
ever sees its SHA-256 hash."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth.passwords import verify_password
from app.config import get_settings
from app.models import AppUser, UserSession

# audit_event.target_id is required; a failed login for an unknown username has no user row.
NO_USER = uuid.UUID(int=0)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(session: Session, username: str, password: str) -> AppUser | None:
    """Returns the user only for an active account with a matching password.

    Every failure is audited with an internal reason; callers must return one generic error.
    """
    user = session.scalar(select(AppUser).where(AppUser.username == username))
    ok = verify_password(user.password_hash if user else None, password)
    if user is None:
        reason = "unknown_user"
    elif not ok:
        reason = "bad_password"
    elif not user.is_active:
        reason = "inactive"
    else:
        return user
    audit(
        session,
        None,
        "anonymous",
        "auth.login_failed",
        "app_user",
        user.id if user else NO_USER,
        metadata={"username": username, "reason": reason},
    )
    return None


def start_session(session: Session, user: AppUser) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
    )
    session.add(row)
    user.last_login_at = now
    session.flush()
    audit(
        session,
        None,
        user.username,
        "auth.login",
        "app_user",
        user.id,
        metadata={"session_id": str(row.id)},
    )
    return token, row


def resolve_session(session: Session, token: str | None) -> tuple[UserSession, AppUser] | None:
    """The live session and its user, or None if missing, expired, revoked or deactivated."""
    if not token:
        return None
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    user = session.get(AppUser, row.user_id)
    if user is None or not user.is_active:
        return None
    return row, user


def end_session(session: Session, row: UserSession, user: AppUser) -> None:
    row.revoked_at = datetime.now(UTC)
    audit(
        session,
        None,
        user.username,
        "auth.logout",
        "app_user",
        user.id,
        metadata={"session_id": str(row.id)},
    )
