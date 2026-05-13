from __future__ import annotations

import mimetypes
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.config import settings
from app.models.user import User
from app.db.session import get_db
from app.utils.upload_urls import is_branding_upload, normalize_upload_relative_path

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)

DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT
LEGACY_AUTH_ALLOWED_PREFIXES = ("sorties-fonds/annexes/",)


def _sanitize_rel_path(raw: str) -> str:
    normalized = os.path.normpath(raw).lstrip(os.sep).replace("\\", "/")
    if normalized.startswith("..") or "/.." in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chemin invalide")
    return normalized


def _extract_tenant_uuid(safe_rel: str) -> str | None:
    parts = safe_rel.split("/", 2)
    if len(parts) < 2 or parts[0] != "tenants":
        return None
    try:
        return str(uuid.UUID(parts[1]))
    except ValueError:
        return None


def _path_requires_tenant_match(safe_rel: str) -> bool:
    return _extract_tenant_uuid(safe_rel) is not None


def _is_legacy_auth_allowed(safe_rel: str) -> bool:
    return any(safe_rel.startswith(prefix) for prefix in LEGACY_AUTH_ALLOWED_PREFIXES)


def _build_internal_response(fs_path: str, safe_rel: str, download: bool = False) -> Response:
    content_type, _ = mimetypes.guess_type(fs_path)
    headers = {"X-Accel-Redirect": f"/_protected_uploads/{safe_rel}"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(fs_path)}"'
    return Response(content=b"", media_type=content_type or "application/octet-stream", headers=headers)


async def _resolve_token_tenant_uuid(raw_token: str, db: AsyncSession) -> str | None:
    try:
        payload = decode_token(raw_token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    org_uuid = payload.get("org_uuid")
    return str(org_uuid).strip() if org_uuid else None


@router.get("/public-uploads/{file_path:path}")
async def serve_public_upload(file_path: str) -> Response:
    safe_rel = _sanitize_rel_path(file_path)
    if not is_branding_upload(normalize_upload_relative_path(safe_rel)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")

    fs_path = os.path.abspath(os.path.join(UPLOAD_ROOT, safe_rel))
    if not fs_path.startswith(UPLOAD_ROOT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chemin invalide")
    if not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")

    return _build_internal_response(fs_path, safe_rel)


@router.get("/secure-uploads/{file_path:path}")
async def serve_secure_upload(
    file_path: str,
    download: bool = Query(default=False),
    token: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Response:
    safe_rel = _sanitize_rel_path(file_path)
    fs_path = os.path.abspath(os.path.join(UPLOAD_ROOT, safe_rel))
    if not fs_path.startswith(UPLOAD_ROOT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chemin invalide")
    if not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")

    raw_token = creds.credentials if creds is not None else token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token_tenant_uuid = await _resolve_token_tenant_uuid(raw_token, db)
    path_tenant_uuid = _extract_tenant_uuid(safe_rel)

    if _path_requires_tenant_match(safe_rel):
        if not token_tenant_uuid or token_tenant_uuid != path_tenant_uuid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    elif not _is_legacy_auth_allowed(safe_rel):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")

    return _build_internal_response(fs_path, safe_rel, download=download)
