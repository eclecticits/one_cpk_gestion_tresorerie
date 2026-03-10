from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.status import HTTP_400_BAD_REQUEST

from app.api.deps import require_roles, get_current_tenant_uuid
from app.core.config import settings

router = APIRouter()

DEFAULT_UPLOAD_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads")
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else os.path.abspath(DEFAULT_UPLOAD_ROOT)


def _ensure_upload_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _save_upload(file: UploadFile, prefix: str, tenant_uuid: str) -> str:
    if not file.filename:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Fichier manquant")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Format de fichier non supporté")
    target_dir = os.path.join(UPLOAD_ROOT, "tenants", str(tenant_uuid), "branding")
    _ensure_upload_dir(target_dir)
    filename = f"{prefix}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as buffer:
        buffer.write(file.file.read())
    return f"/uploads/tenants/{tenant_uuid}/branding/{filename}"


@router.post("/uploads/logo", dependencies=[Depends(require_roles(["admin"]))])
async def upload_logo(
    file: UploadFile = File(...),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict:
    url = _save_upload(file, "logo", tenant_uuid)
    return {"url": url}


@router.post("/uploads/stamp", dependencies=[Depends(require_roles(["admin"]))])
async def upload_stamp(
    file: UploadFile = File(...),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict:
    url = _save_upload(file, "stamp", tenant_uuid)
    return {"url": url}
