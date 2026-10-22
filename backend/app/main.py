import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin_routes import router as admin_router
from app.api.portal_routes import router as portal_router
from app.api.routes import authed as authed_router
from app.api.routes import router
from app.api.verify_routes import router as verify_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.errors import AppError, app_error_handler

log = logging.getLogger("silobreaker")

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "silobreaker"

app = FastAPI(
    title="SiloBreaker API",
    version="0.1.0",
    description="Detect knowledge risk -> Capture missing context -> Verify transfer",
)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(authed_router)
app.include_router(verify_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(portal_router)


@app.middleware("http")
async def require_csrf_header(request: Request, call_next):
    """Cookie sessions need CSRF protection: a cross-site form cannot set this header, and a
    cross-site script cannot send it without passing CORS preflight."""
    if request.method in WRITE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "csrf_header_missing",
                    "detail": "write requests must send X-Requested-With: silobreaker",
                }
            },
        )
    return await call_next(request)


@app.middleware("http")
async def operation_log(request: Request, call_next):
    """Logs operation ID, route, status and duration. Never logs evidence bodies."""
    op_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = op_id
    log.info(
        "op=%s %s %s -> %s in %.0f ms",
        op_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - start) * 1000,
    )
    return response
