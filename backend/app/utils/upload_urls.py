from __future__ import annotations

from app.core.config import settings

API_V1_PREFIX = "/api/v1"


def normalize_upload_relative_path(path: str | None) -> str | None:
    if not path:
        return None
    raw = str(path).strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return None
    if raw.startswith(f"{API_V1_PREFIX}/public-uploads/"):
        return raw.replace(f"{API_V1_PREFIX}/public-uploads/", "", 1).lstrip("/")
    if raw.startswith(f"{API_V1_PREFIX}/secure-uploads/"):
        return raw.replace(f"{API_V1_PREFIX}/secure-uploads/", "", 1).lstrip("/")
    if raw.startswith("/uploads/"):
        return raw.replace("/uploads/", "", 1).lstrip("/")
    return raw.lstrip("/")


def is_branding_upload(rel_path: str | None) -> bool:
    if not rel_path:
        return False
    normalized = rel_path.strip().lstrip("/")
    return normalized.startswith("tenants/") and "/branding/" in normalized


def build_public_upload_url(path: str | None) -> str | None:
    if not path:
        return path
    if settings.serve_uploads_publicly:
        return path
    rel_path = normalize_upload_relative_path(path)
    if not is_branding_upload(rel_path):
        return path
    return f"{API_V1_PREFIX}/public-uploads/{rel_path}"
