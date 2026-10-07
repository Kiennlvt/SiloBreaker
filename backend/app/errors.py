from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Stable, machine-readable error. 409 = conflict/state, 422 = invalid input."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content={"error": {"code": exc.code, "detail": exc.detail}}
    )
