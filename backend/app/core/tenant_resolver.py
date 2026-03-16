from __future__ import annotations

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation

_RESERVED_SUBDOMAINS = {"www", "app", "admin", "signup"}


def is_admin_host(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1"}:
        return False
    if host.endswith(".localhost"):
        return False
    parts = [part for part in host.split(".") if part]
    if not parts:
        return False
    return parts[0] == "admin"


def _normalize_hint(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def extract_tenant_hint(request: Request, header_value: str | None) -> str | None:
    hint = _normalize_hint(header_value)
    if hint:
        return hint

    host = (request.url.hostname or "").lower()
    if not host:
        return None
    if host in {"localhost", "127.0.0.1"}:
        return None

    parts = [part for part in host.split(".") if part]
    if not parts:
        return None

    if host.endswith(".localhost"):
        sub = parts[0]
        return None if sub in _RESERVED_SUBDOMAINS else sub

    if len(parts) <= 2:
        sub = parts[0]
        return None if sub in _RESERVED_SUBDOMAINS else None

    subdomain = parts[0]
    return None if subdomain in _RESERVED_SUBDOMAINS else subdomain


async def resolve_tenant(db: AsyncSession, hint: str | None) -> Organisation | None:
    normalized = _normalize_hint(hint)
    if not normalized:
        return None

    if normalized.isdigit():
        res = await db.execute(select(Organisation).where(Organisation.id == int(normalized)))
    else:
        res = await db.execute(select(Organisation).where(Organisation.slug == normalized))

    org = res.scalar_one_or_none()
    if org is None or org.is_active is False:
        return None
    return org
