from __future__ import annotations

import uuid
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions, Role

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
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

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

    return user


def require_roles(allowed: Iterable[str]):
    allowed_set = set(allowed)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_set:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dep


def has_permission(permission_code: str):
    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Legacy admin short-circuit
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
