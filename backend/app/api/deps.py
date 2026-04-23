from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.audit_context import set_audit_user_id, set_audit_org_id
from app.core.tenant_context import set_current_tenant_id
from app.core.tenant_resolver import (
    describe_tenant_resolution,
    extract_tenant_hint,
    has_tenant_hint_conflict,
    is_admin_host,
    resolve_tenant,
)
from app.core.config import settings
from app.core.permissions import resolve_permission_code
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions, Role
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.user_service import user_services

bearer_scheme = HTTPBearer(auto_error=False)

_saas_status_cache: dict[int, tuple[str, float]] = {}
logger = logging.getLogger("onec_cpk_api")


def _normalize_plan_status(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).strip().upper()


def _build_saas_status_url(tenant_id: int) -> str | None:
    base = (settings.saas_console_base_url or "").strip()
    if not base:
        return None
    base = base.rstrip("/")
    if base.endswith("/api/v1"):
        api_base = base
    elif base.endswith("/api"):
        api_base = f"{base}/v1"
    else:
        api_base = f"{base}/api/v1"
    path = (settings.saas_status_path or "/tenants/{tenant_id}/status").strip() or "/tenants/{tenant_id}/status"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{api_base}{path.format(tenant_id=tenant_id)}"


async def _fetch_saas_status(tenant_id: int) -> str | None:
    if not settings.saas_console_base_url or not settings.saas_internal_key:
        return None
    url = _build_saas_status_url(tenant_id)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return None

    if isinstance(payload, dict):
        status_value = payload.get("status") or payload.get("plan_status")
    else:
        status_value = None
    return _normalize_plan_status(status_value)


async def get_cached_saas_status(tenant_id: int) -> str | None:
    ttl = max(30, int(settings.saas_status_cache_ttl_seconds or 0))
    now = time.time()
    cached = _saas_status_cache.get(tenant_id)
    if cached and cached[1] > now:
        return cached[0]
    status_value = await _fetch_saas_status(tenant_id)
    if status_value:
        _saas_status_cache[tenant_id] = (status_value, now + ttl)
    return status_value


def clear_saas_status_cache(tenant_id: int | None = None) -> None:
    if tenant_id is None:
        _saas_status_cache.clear()
        return
    _saas_status_cache.pop(tenant_id, None)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = uuid.UUID(sub)
    org_id = payload.get("org_id")
    org_uuid = payload.get("org_uuid")
    org_slug = payload.get("org_slug")
    plan_status = _normalize_plan_status(payload.get("plan_status"))
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    admin_host = is_admin_host(request)
    is_super_admin = (user.role or "").lower() == "super_admin"

    if admin_host and not is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin requis")

    if user.organisation_id and not org_id:
        org_id = user.organisation_id
    if org_id is None and not (admin_host and is_super_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")

    if has_tenant_hint_conflict(request, x_tenant_id):
        logger.warning(
            "Tenant conflict rejected: host=%s header=%s path=%s user_id=%s",
            request.url.hostname,
            x_tenant_id,
            request.url.path,
            user.id,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conflit de tenant")

    tenant_hint = extract_tenant_hint(request, x_tenant_id)
    resolution = describe_tenant_resolution(request, x_tenant_id)
    if tenant_hint:
        if tenant_hint.isdigit():
            hinted_id = int(tenant_hint)
            if not is_super_admin and org_id is not None and org_id != hinted_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")
            org_id = hinted_id if is_super_admin else (org_id or hinted_id)
        else:
            if org_slug and tenant_hint == org_slug and not is_super_admin:
                pass
            else:
                hinted_org = await resolve_tenant(db, tenant_hint)
                if hinted_org is None:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")
                if not is_super_admin and org_id is not None and hinted_org.id != org_id:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")
                if is_super_admin:
                    org_id = hinted_org.id
                    org_uuid = str(hinted_org.uuid)
                    plan_status = hinted_org.status_abonnement
                    org_slug = hinted_org.slug
                else:
                    org_id = org_id or hinted_org.id
                    org_uuid = org_uuid or str(hinted_org.uuid)
                    plan_status = plan_status or hinted_org.status_abonnement
                    org_slug = org_slug or hinted_org.slug

    if (org_uuid is None or plan_status is None) and org_id is not None:
        org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
        org = org_res.scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation introuvable")
        org_uuid = str(org.uuid)
        plan_status = _normalize_plan_status(org.status_abonnement)

    if admin_host and is_super_admin:
        request.state.tenant_id = None
        request.state.tenant_uuid = None
        set_current_tenant_id(None)
    else:
        request.state.tenant_id = org_id
        request.state.tenant_uuid = org_uuid
        set_current_tenant_id(org_id)
    request.state.plan_status = plan_status

    logger.info(
        "Tenant resolved: path=%s host=%s admin_host=%s source=%s host_hint=%s header_hint=%s effective_hint=%s tenant_id=%s tenant_slug=%s user_id=%s role=%s",
        request.url.path,
        resolution["host"],
        admin_host,
        resolution["source"],
        resolution["host_hint"],
        resolution["header_hint"],
        resolution["effective_hint"],
        org_id,
        org_slug,
        user.id,
        user.role,
    )

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not (admin_host and is_super_admin) and org_id is not None:
            saas_status = await get_cached_saas_status(org_id)
            if saas_status:
                plan_status = saas_status
                request.state.plan_status = plan_status
        if not (admin_host and is_super_admin) and plan_status not in {"ACTIVE", "TRIAL"}:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Abonnement expiré. Passage en lecture seule. Veuillez régulariser via ePaieLink.",
            )

    if user.must_change_password or user.is_first_login or not user.is_email_verified:
        path = request.url.path
        allowed = {
            "/api/v1/auth/change-password",
            "/api/v1/auth/logout",
            "/api/v1/auth/me",
            "/api/v1/auth/refresh",
            "/api/v1/auth/request-password-reset",
            "/api/v1/auth/request-password-change",
            "/api/v1/auth/confirm-password-change",
        }
        if path not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password verification required")

    set_audit_user_id(user.id)
    set_audit_org_id(org_id)
    return user


async def get_current_tenant_id(
    request: Request,
    user: User = Depends(get_current_user),
) -> int:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")
    return tenant_id


async def get_public_tenant_id(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> int:
    """Résout le tenant sans exiger d'authentification (pour les pages publiques)."""
    tenant_hint = extract_tenant_hint(request, x_tenant_id)
    if not tenant_hint:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation non identifiée")

    org = await resolve_tenant(db, tenant_hint)
    if not org:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")

    # On pré-remplit le contexte tenant pour les services qui pourraient en avoir besoin
    request.state.tenant_id = org.id
    request.state.tenant_uuid = str(org.uuid)
    set_current_tenant_id(org.id)

    return org.id


async def get_current_tenant_uuid(
    request: Request,
    user: User = Depends(get_current_user),
) -> str:
    tenant_uuid = getattr(request.state, "tenant_uuid", None)
    if not tenant_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")
    return str(tenant_uuid)


def require_roles(allowed: Iterable[str]):
    allowed_set = set(allowed)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if (user.role or "").lower() == "super_admin":
            return user
        if user.role not in allowed_set:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dep


async def require_super_admin(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    if (user.role or "").lower() != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin requis")
    # Disable tenant scoping for super-admin endpoints.
    set_current_tenant_id(None)
    request.state.tenant_id = None
    return user


def has_permission(permission_code: str):
    resolved_permission_code = resolve_permission_code(permission_code)

    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Legacy admin short-circuit
        if (user.role or "").lower() == "super_admin":
            return user
        if (user.role or "").lower() == "admin":
            return user
        if resolved_permission_code == "menu_services":
            service_res = await db.execute(
                select(user_services.c.service_id).where(user_services.c.user_id == user.id).limit(1)
            )
            if user.service_id or service_res.scalar_one_or_none() is not None:
                return user
        if not user.role_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions requises")

        perm_query = (
            select(Permission.id)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == user.role_id)
            .where(Permission.code == resolved_permission_code)
        )
        res = await db.execute(perm_query)
        if res.scalar_one_or_none() is None:
            # allow admin by role table if role_id resolves to admin
            role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
            role_code = (role_res.scalar_one_or_none() or "").lower()
            if role_code != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Privilèges insuffisants ({resolved_permission_code})",
                )
        return user

    return _dep


async def require_ai_enabled(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == user.organisation_id).limit(1)
    )
    settings_row = res.scalar_one_or_none()
    if not settings_row or not settings_row.is_ai_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Module IA non activé")
    return user
