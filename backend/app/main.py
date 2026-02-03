from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.config import settings

app = FastAPI(title="ONEC/CPK Tresorerie API")
logger = logging.getLogger("onec_cpk_api")

default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
origins = default_origins + settings.parsed_cors_origins()
origins = list(dict.fromkeys(origins))
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(router)


@app.on_event("startup")
async def log_database_url() -> None:
    logger.info("DATABASE_URL (runtime): %s", settings.database_url)


@app.get("/")
async def root() -> dict:
    return {"name": "onec-cpk-api", "version": "v1"}
