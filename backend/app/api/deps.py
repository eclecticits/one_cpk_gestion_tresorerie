from __future__ import annotations

import logging
import uuid
from typing import Iterable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from sqlalchemy import outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_user import AuthUser, cached_permission_codes, cached_service_ids
from app.core.cache import cache_delete, cache_delete_pattern, cache_get, cache_set
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
from app.models.commission_member import CommissionMember
from app.models.service import Service

bearer_scheme = HTTPBearer(auto_error=False)
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


AUTH_CONTEXT_CACHE_PREFIX = "authctx:v1"


def _auth_context_cache_key(user_id: uuid.UUID) -> str:
    # Le contexte ne dépend que de l'utilisateur : ni le tenant hint ni l'org du
    # token n'en modifient le contenu. Une clé par utilisateur évite de
    # multiplier les entrées (et rend l'invalidation ciblée exacte).
    return f"{AUTH_CONTEXT_CACHE_PREFIX}:{user_id}"


async def invalidate_auth_context_cache(user_id: uuid.UUID | str | None = None) -> int:
    """Purge le contexte d'un utilisateur, ou tout le namespace si ``user_id`` est None.

    À appeler après tout changement de rôle, de permissions de rôle,
    d'affectation de service ou d'état d'activation — sans quoi la modification
    ne prend effet qu'à l'expiration du TTL.
    """
    if user_id is not None:
        return 1 if await cache_delete(_auth_context_cache_key(user_id)) else 0
    return await cache_delete_pattern(f"{AUTH_CONTEXT_CACHE_PREFIX}:*")


async def _load_auth_context(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> dict | None:
    org_join = outerjoin(User, Organisation, User.organisation_id == Organisation.id)
    # Colonnes labellisées : User.id et Organisation.id porteraient sinon le même
    # nom, d'où l'accès positionnel — fragile au moindre ajout de colonne.
    res = await db.execute(
        select(
            User.id.label("user_id"),
            User.email.label("email"),
            User.nom.label("nom"),
            User.prenom.label("prenom"),
            User.role.label("role"),
            User.role_id.label("role_id"),
            User.service_id.label("service_id"),
            User.organisation_id.label("organisation_id"),
            User.active.label("active"),
            User.must_change_password.label("must_change_password"),
            User.is_first_login.label("is_first_login"),
            User.is_email_verified.label("is_email_verified"),
            Organisation.id.label("org_id"),
            Organisation.uuid.label("org_uuid"),
            Organisation.slug.label("org_slug"),
            Organisation.status_abonnement.label("status_abonnement"),
        )
        .select_from(org_join)
        .where(User.id == user_id)
    )
    row = res.first()
    if row is None:
        return None

    role_name = (row.role or "").lower()
    permissions: list[str] = []
    if row.role_id is not None and role_name not in {"admin", "super_admin"}:
        permissions = (
            await db.execute(
                select(Permission.code)
                .join(role_permissions, role_permissions.c.permission_id == Permission.id)
                .where(role_permissions.c.role_id == row.role_id)
            )
        ).scalars().all()

    service_ids: set[int] = set()
    if row.service_id is not None:
        service_ids.add(row.service_id)
    service_ids.update(
        (
            await db.execute(
                select(user_services.c.service_id).where(user_services.c.user_id == user_id)
            )
        ).scalars().all()
    )
    commission_query = select(CommissionMember.service_id).join(Service, Service.id == CommissionMember.service_id).where(
        CommissionMember.user_id == user_id
    )
    if row.organisation_id is not None:
        commission_query = commission_query.where(Service.organisation_id == row.organisation_id)
    service_ids.update((await db.execute(commission_query)).scalars().all())

    return {
        "user_id": str(row.user_id),
        "email": row.email,
        "nom": row.nom,
        "prenom": row.prenom,
        "role": row.role,
        "role_id": row.role_id,
        "service_id": row.service_id,
        "organisation_id": row.organisation_id,
        "active": row.active,
        "must_change_password": row.must_change_password,
        "is_first_login": row.is_first_login,
        "is_email_verified": row.is_email_verified,
        "org_id": row.org_id,
        "org_uuid": str(row.org_uuid) if row.org_uuid else None,
        "org_slug": row.org_slug,
        "plan_status": _normalize_plan_status(row.status_abonnement),
        "permissions": sorted(set(permissions)),
        "service_ids": sorted(service_ids),
    }


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
    """Cache du statut SaaS dans Redis (multi-worker safe).

    Remplace l'ancien dict in-process qui était perdu à chaque restart
    et non partagé entre les workers Gunicorn.
    """
    ttl = max(30, int(settings.saas_status_cache_ttl_seconds or 0))
    cache_key = f"saas:status:{tenant_id}"

    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    status_value = await _fetch_saas_status(tenant_id)
    if status_value:
        await cache_set(cache_key, status_value, ttl=ttl)
    return status_value


async def clear_saas_status_cache(tenant_id: int | None = None) -> None:
    if tenant_id is None:
        from app.core.cache import cache_delete_pattern
        await cache_delete_pattern("saas:status:*")
    else:
        await cache_delete(f"saas:status:{tenant_id}")


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
    tenant_hint = extract_tenant_hint(request, x_tenant_id)
    cache_key = _auth_context_cache_key(user_id)
    ctx = await cache_get(cache_key) if settings.auth_context_cache_enabled else None
    if ctx is None:
        ctx = await _load_auth_context(db, user_id=user_id)
        if ctx is not None and settings.auth_context_cache_enabled:
            await cache_set(cache_key, ctx, ttl=settings.auth_context_cache_ttl_seconds)

    if ctx is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")
    user = AuthUser.from_context(ctx)
    if not user.active:
        await cache_delete(cache_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    org_uuid = org_uuid or ctx.get("org_uuid")
    org_slug = org_slug or ctx.get("org_slug")
    plan_status = plan_status or _normalize_plan_status(ctx.get("plan_status"))

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
        if ctx.get("org_id") == org_id:
            org_uuid = ctx.get("org_uuid")
            plan_status = _normalize_plan_status(ctx.get("plan_status"))
        else:
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

    if is_super_admin and org_id is not None and user.organisation_id != org_id:
        # AuthUser est un objet détaché : simple affectation, pas de manipulation
        # d'état ORM.
        user.organisation_id = org_id

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
    set_current_tenant_id(tenant_id)
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


async def require_national_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Réservé à l'administration nationale ONEC.

    Les registres partagés entre toutes les organisations (dénominations,
    experts-comptables, historique des imports) ne doivent être modifiés que par
    le super_admin ou l'admin de l'organisation « CN » (Conseil National).
    Empêche qu'un admin d'un autre tenant altère des données nationales.
    """
    role = (user.role or "").lower()
    if role == "super_admin":
        return user
    if role == "admin" and user.organisation_id:
        org_res = await db.execute(
            select(Organisation.slug).where(Organisation.id == user.organisation_id)
        )
        slug = (org_res.scalar_one_or_none() or "").lower()
        if slug == "cn":
            return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Action réservée à l'administration nationale (Conseil National).",
    )


def has_any_permission(permission_codes: Iterable[str]):
    # Maintain both raw and resolved codes to be safe
    raw_codes = list(permission_codes)
    resolved_codes = [resolve_permission_code(c) for c in raw_codes]
    all_requested_codes = list(set(raw_codes + resolved_codes))

    def _access_denied_detail() -> str:
        return (
            "Accès refusé : votre compte n'a pas les droits nécessaires. "
            f"Permission requise : {', '.join(raw_codes)}."
        )

    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Legacy admin short-circuit
        role_name = (user.role or "").lower()
        if role_name in {"super_admin", "admin"}:
            return user
        user_permissions = cached_permission_codes(user)
        user_service_ids = cached_service_ids(user)
        if user_permissions is not None and user_permissions.intersection(all_requested_codes):
            return user

        service_related = {"services", "menu_services"}
        service_permission_requested = any(c in service_related for c in all_requested_codes)

        async def _belongs_to_a_service() -> bool:
            if user.service_id or user_service_ids:
                return True
            # user_service_ids non nul signifie que le contexte a déjà résolu
            # l'appartenance : inutile de réinterroger la base.
            if user_service_ids is not None:
                return False
            service_res = await db.execute(
                select(user_services.c.service_id).where(user_services.c.user_id == user.id).limit(1)
            )
            return service_res.scalar_one_or_none() is not None

        # If user has no role assigned, they can't have permissions (unless they have a service)
        if not user.role_id:
            if service_permission_requested and await _belongs_to_a_service():
                return user
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_access_denied_detail())

        # Les permissions du contexte sont complètes : le refus est décidable
        # sans requête supplémentaire.
        if user_permissions is None:
            perm_query = (
                select(Permission.code)
                .join(role_permissions, role_permissions.c.permission_id == Permission.id)
                .where(role_permissions.c.role_id == user.role_id)
                .where(Permission.code.in_(all_requested_codes))
            )
            if (await db.execute(perm_query)).scalars().all():
                return user

        # Extra check for service membership if service permissions requested but not in role
        if service_permission_requested and await _belongs_to_a_service():
            return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_access_denied_detail(),
        )

    return _dep


def has_permission(permission_code: str):
    resolved_permission_code = resolve_permission_code(permission_code)
    access_denied_detail = (
        "Accès refusé : votre compte n'a pas les droits nécessaires. "
        f"Permission requise : {resolved_permission_code}."
    )

    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Legacy admin short-circuit
        if (user.role or "").lower() == "super_admin":
            return user
        if (user.role or "").lower() == "admin":
            return user
        user_permissions = cached_permission_codes(user)
        user_service_ids = cached_service_ids(user)
        if user_permissions is not None and resolved_permission_code in user_permissions:
            return user
        if resolved_permission_code == "menu_services":
            if user.service_id or user_service_ids:
                return user
            # user_service_ids non nul signifie que le contexte a déjà résolu
            # l'appartenance : inutile de réinterroger la base.
            if user_service_ids is None:
                service_res = await db.execute(
                    select(user_services.c.service_id).where(user_services.c.user_id == user.id).limit(1)
                )
                if service_res.scalar_one_or_none() is not None:
                    return user
        if not user.role_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=access_denied_detail)

        # Les permissions du contexte sont complètes : quand elles sont
        # disponibles, l'absence du code vaut refus, sans requête.
        granted = False
        if user_permissions is None:
            perm_query = (
                select(Permission.id)
                .join(role_permissions, role_permissions.c.permission_id == Permission.id)
                .where(role_permissions.c.role_id == user.role_id)
                .where(Permission.code == resolved_permission_code)
            )
            granted = (await db.execute(perm_query)).scalar_one_or_none() is not None

        if not granted:
            # allow admin by role table if role_id resolves to admin
            role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
            role_code = (role_res.scalar_one_or_none() or "").lower()
            if role_code != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=access_denied_detail,
                )
        return user

    return _dep


async def require_ai_enabled(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Le module IA est-il activé pour cette organisation ?

    Les super_admin contournent toujours cette vérification, comme pour
    `require_module` juste en dessous : ils opèrent au-dessus des organisations
    et ne peuvent pas être arrêtés par l'activation d'un module dans l'une
    d'elles — notamment quand ils y interviennent pour la réparer.
    """
    if (user.role or "").lower() == "super_admin":
        return user

    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == user.organisation_id).limit(1)
    )
    settings_row = res.scalar_one_or_none()
    if not settings_row or not settings_row.is_ai_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Module IA non activé")
    return user


def require_module(module_name: str):
    """Vérifie que le module est activé dans modules_config pour le tenant courant.

    Si modules_config est absent ou ne mentionne pas le module, l'accès est accordé
    (rétrocompatibilité avec les organisations créées avant la gestion des modules).
    Les super_admin contournent toujours cette vérification.
    """
    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if (user.role or "").lower() == "super_admin":
            return user

        org_id = user.organisation_id
        if org_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")

        res = await db.execute(
            select(OrganisationSettings)
            .where(OrganisationSettings.organisation_id == org_id)
            .limit(1)
        )
        org_settings = res.scalar_one_or_none()
        modules_config: dict = (org_settings.modules_config or {}) if org_settings else {}
        module_cfg = modules_config.get(module_name)

        # Si le module n'est pas configuré → accès accordé (rétrocompatibilité)
        if module_cfg is not None and not module_cfg.get("enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Module '{module_name}' non activé pour cette organisation.",
            )
        return user

    return _dep
