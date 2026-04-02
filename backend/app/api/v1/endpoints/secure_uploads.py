from __future__ import annotations

import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_current_tenant_uuid, get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter()

DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT


def _sanitize_rel_path(raw: str) -> str:
    normalized = os.path.normpath(raw).lstrip(os.sep).replace("\\", "/")
    if normalized.startswith("..") or "/.." in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chemin invalide")
    return normalized


@router.get("/secure-uploads/{file_path:path}")
async def serve_secure_upload(
    file_path: str,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> Response:
    del user
    safe_rel = _sanitize_rel_path(file_path)
    tenant_prefix = f"tenants/{tenant_uuid}/"
    if not safe_rel.startswith(tenant_prefix):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    fs_path = os.path.abspath(os.path.join(UPLOAD_ROOT, safe_rel))
    if not fs_path.startswith(UPLOAD_ROOT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chemin invalide")
    if not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")

    content_type, _ = mimetypes.guess_type(fs_path)
    headers = {"X-Accel-Redirect": f"/_protected_uploads/{safe_rel}"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(fs_path)}"'
    return Response(content=b"", media_type=content_type or "application/octet-stream", headers=headers)
