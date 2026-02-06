from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.status import HTTP_400_BAD_REQUEST

from app.api.deps import require_roles

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads")
UPLOAD_DIR = os.path.abspath(UPLOAD_DIR)


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_upload(file: UploadFile, prefix: str) -> str:
    if not file.filename:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Fichier manquant")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Format de fichier non supporté")
    _ensure_upload_dir()
    filename = f"{prefix}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, filename)
    with open(dest_path, "wb") as buffer:
        buffer.write(file.file.read())
    return f"/uploads/{filename}"


@router.post("/uploads/logo", dependencies=[Depends(require_roles(["admin"]))])
async def upload_logo(file: UploadFile = File(...)) -> dict:
    url = _save_upload(file, "logo")
    return {"url": url}


@router.post("/uploads/stamp", dependencies=[Depends(require_roles(["admin"]))])
async def upload_stamp(file: UploadFile = File(...)) -> dict:
    url = _save_upload(file, "stamp")
    return {"url": url}
