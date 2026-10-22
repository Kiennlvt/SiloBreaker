from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes import tx
from app.auth import service
from app.config import get_settings
from app.errors import AppError
from app.models import AppUser

router = APIRouter(prefix="/api/auth")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


def _user(user: AppUser) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "person_id": user.person_id,
    }


def _token(request: Request) -> str | None:
    return request.cookies.get(get_settings().session_cookie_name)


def current_user(token: str | None = Depends(_token), session: Session = Depends(tx)) -> AppUser:
    found = service.resolve_session(session, token)
    if found is None:
        raise AppError(401, "not_authenticated", "Sign in required")
    return found[1]


@router.post("/login")
def login(body: LoginIn, response: Response, session: Session = Depends(tx)) -> dict:
    user = service.authenticate(session, body.username, body.password)
    if user is None:
        # Keep the failure audit even though the request ends in an error (tx rolls back).
        session.commit()
        raise AppError(401, "invalid_credentials", "Invalid username or password")
    token, row = service.start_session(session, user)
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    return {"user": _user(user), "expires_at": row.expires_at.isoformat()}


@router.post("/logout", status_code=204)
def logout(token: str | None = Depends(_token), session: Session = Depends(tx)) -> Response:
    """Revokes the current session, if any. Always clears the cookie."""
    found = service.resolve_session(session, token)
    if found is not None:
        service.end_session(session, *found)
    response = Response(status_code=204)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.get("/me")
def me(user: AppUser = Depends(current_user)) -> dict:
    return {"user": _user(user)}
