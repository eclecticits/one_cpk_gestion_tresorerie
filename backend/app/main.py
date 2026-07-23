from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import router
from app.core.cache import close_redis, init_redis
from app.core.config import settings
from app.core.limiter import limiter
from app.core.alerts import ErrorTrackingMiddleware, internal_error_handler
from app.core.metrics import setup_metrics
from app.middleware.timing import SlowRequestMiddleware
from app.utils.scheduler import (
    start_weekly_report_scheduler,
    start_monthly_report_scheduler,
    start_billing_guard_scheduler,
)
from app.core.audit_context import set_audit_user_id, set_audit_org_id
from app.core.tenant_context import set_current_tenant_id

app = FastAPI(
    title="ONEC Smart API",
    description="Plateforme intelligente de gestion intégrée de l'ONEC-RDC",
    swagger_ui_parameters={"deepLinking": False},
)
logger = logging.getLogger("onec_cpk_api")

default_origins = []
if settings.env.lower() not in {"prod", "production"}:
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
origins = default_origins + settings.parsed_cors_origins()
origins = list(dict.fromkeys(origins))
cors_origin_regex = (settings.cors_origin_regex or "").strip() or None
if origins or cors_origin_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SlowRequestMiddleware)
app.add_middleware(ErrorTrackingMiddleware)

setup_metrics(app)

UPLOAD_DIR = settings.upload_dir or os.path.join(os.path.dirname(__file__), "uploads")
UPLOAD_DIR = os.path.abspath(UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)
if settings.serve_uploads_publicly:
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_event() -> None:
    await init_redis()
    start_weekly_report_scheduler()
    start_monthly_report_scheduler()
    start_billing_guard_scheduler()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await close_redis()


@app.get("/")
async def root() -> dict:
    return {"name": "onec-cpk-api", "version": "v1"}


@app.middleware("http")
async def audit_context_middleware(request, call_next):
    set_audit_user_id(None)
    set_audit_org_id(None)
    set_current_tenant_id(None)
    return await call_next(request)
