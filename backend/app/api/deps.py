from __future__ import annotations

import uuid
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.audit_context import set_audit_user_id, set_audit_org_id
from app.core.tenant_context import set_current_tenant_id
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions, Role
from app.models.organisation import Organisation

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
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
    plan_status = payload.get("plan_status")
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    if user.organisation_id and not org_id:
        org_id = user.organisation_id
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")

    if org_uuid is None or plan_status is None:
        org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
        org = org_res.scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation introuvable")
        org_uuid = str(org.uuid)
        plan_status = org.status_abonnement

    request.state.tenant_id = org_id
    request.state.tenant_uuid = org_uuid
    request.state.plan_status = plan_status
    set_current_tenant_id(org_id)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if plan_status not in {"ACTIVE", "TRIAL"}:
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
    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Legacy admin short-circuit
        if (user.role or "").lower() == "super_admin":
            return user
        if (user.role or "").lower() == "admin":
            return user
        if not user.role_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions requises")

        perm_query = (
            select(Permission.id)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == user.role_id)
            .where(Permission.code == permission_code)
        )
        res = await db.execute(perm_query)
        if res.scalar_one_or_none() is None:
            # allow admin by role table if role_id resolves to admin
            role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
            role_code = (role_res.scalar_one_or_none() or "").lower()
            if role_code != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Privilèges insuffisants ({permission_code})",
                )
        return user

    return _dep
