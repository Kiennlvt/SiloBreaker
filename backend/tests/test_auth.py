"""Web accounts: login, logout, session cookie, deactivation, demo reset."""

import pytest
from sqlalchemy import func, select, update

from app.db import get_session
from app.models import AppUser, AuditEvent, UserSession
from app.seed_users import DEMO_USERS, seed_users


def _db():
    return next(get_session())


@pytest.fixture
def users(client):
    s = _db()
    try:
        seed_users(s)
        s.commit()
    finally:
        s.close()
    client.cookies.clear()
    return client


def _login(c, username="alice", password="Alice@123"):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def _actions():
    s = _db()
    try:
        q = select(AuditEvent.action, AuditEvent.actor_id, AuditEvent.metadata_).order_by(
            AuditEvent.id
        )
        return s.execute(q).all()
    finally:
        s.close()


def test_login_success_sets_httponly_cookie_and_me_returns_user(users):
    r = _login(users)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "alice"
    assert r.json()["user"]["person_id"] == "alice"
    assert r.json()["user"]["role"] == "member"
    assert "password_hash" not in r.json()["user"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("sb_session=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Max-Age=28800" in cookie

    me = users.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"
    assert ("auth.login", "alice") in [(a, actor) for a, actor, _ in _actions()]


def test_session_stores_only_token_hash(users):
    _login(users)
    token = users.cookies.get("sb_session")
    s = _db()
    try:
        hashes = s.scalars(select(UserSession.token_hash)).all()
    finally:
        s.close()
    assert hashes and token not in hashes


def test_wrong_password_and_unknown_user_get_same_401(users):
    bad_pw = _login(users, "alice", "wrong")
    no_user = _login(users, "mallory", "Alice@123")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()
    assert bad_pw.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in bad_pw.headers
    assert users.get("/api/auth/me").status_code == 401

    failed = [m for a, _, m in _actions() if a == "auth.login_failed"]
    assert {m["reason"] for m in failed} == {"bad_password", "unknown_user"}
    assert all("password" not in m for m in failed)


def test_password_hash_does_not_contain_password(users):
    s = _db()
    try:
        rows = {u.username: u.password_hash for u in s.scalars(select(AppUser))}
    finally:
        s.close()
    for spec in DEMO_USERS:
        h = rows[spec["username"]]
        assert h.startswith("$argon2")
        assert spec["password"] not in h


def test_logout_revokes_session_and_old_cookie_is_rejected(users):
    _login(users)
    token = users.cookies.get("sb_session")
    r = users.post("/api/auth/logout")
    assert r.status_code == 204
    users.cookies.clear()
    users.cookies.set("sb_session", token)
    assert users.get("/api/auth/me").status_code == 401
    assert "auth.logout" in [a for a, _, _ in _actions()]


def test_inactive_account_cannot_log_in_or_keep_session(users):
    _login(users, "bob", "Bob@123")
    assert users.get("/api/auth/me").status_code == 200
    s = _db()
    try:
        s.execute(update(AppUser).where(AppUser.username == "bob").values(is_active=False))
        s.commit()
    finally:
        s.close()
    assert users.get("/api/auth/me").status_code == 401
    r = _login(users, "bob", "Bob@123")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_seed_is_idempotent(users):
    s = _db()
    try:
        assert {o for _, o in seed_users(s)} == {"updated"}
        s.commit()
        assert s.scalar(select(func.count()).select_from(AppUser)) == len(DEMO_USERS)
    finally:
        s.close()


def test_demo_reset_keeps_users_and_sessions(users):
    _login(users)
    assert users.post("/api/demo/reset").status_code == 200
    assert users.get("/api/auth/me").json()["user"]["username"] == "alice"
    assert _login(users, "admin", "Admin@123").status_code == 200
