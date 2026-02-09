from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

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

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
UPLOAD_DIR = os.path.abspath(UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> dict:
    return {"name": "onec-cpk-api", "version": "v1"}
