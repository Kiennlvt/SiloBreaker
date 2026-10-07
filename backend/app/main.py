import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.errors import AppError, app_error_handler

log = logging.getLogger("silobreaker")

app = FastAPI(
    title="SiloBreaker API",
    version="0.1.0",
    description="Detect knowledge risk -> Capture missing context -> Verify transfer",
)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


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
