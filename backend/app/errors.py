from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Stable, machine-readable error. 409 = conflict/state, 422 = invalid input.

    `extra` carries safe identifiers the client needs to recover, e.g. the attempt ID
    of an answer that was stored before its assessment failed.
    """

    def __init__(self, status: int, code: str, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra or {}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "detail": exc.detail, **exc.extra}},
    )
