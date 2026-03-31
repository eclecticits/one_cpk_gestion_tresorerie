from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_service import user_services
from app.models.rbac import Permission, role_permissions


async def get_user_service_ids(db: AsyncSession, user: User) -> list[int]:
    if user is None:
        return []

    res = await db.execute(
        select(user_services.c.service_id).where(user_services.c.user_id == user.id)
    )
    ids = [row[0] for row in res.all()]
    if user.service_id and user.service_id not in ids:
        ids.append(user.service_id)
    return ids


async def user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    if user is None:
        return False
    role = (user.role or "").lower().replace("-", "_")
    if role in {"admin", "super_admin"}:
        return True
    if not user.role_id:
        return False
    perm_query = (
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
        .where(Permission.code == permission_code)
    )
    res = await db.execute(perm_query)
    return res.scalar_one_or_none() is not None


async def can_view_all_services(db: AsyncSession, user: User) -> bool:
    return await user_has_permission(db, user, "can_view_all_services")
