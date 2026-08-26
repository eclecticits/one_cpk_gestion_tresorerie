from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_member import CommissionMember
from app.models.service import Service
from app.models.user import User
from app.models.user_service import user_services
from app.models.rbac import Permission, role_permissions
from app.core.auth_user import AuthUser, cached_permission_codes, cached_service_ids
from app.core.permissions import resolve_permission_code


async def has_module_menu_access(
    db: AsyncSession,
    user: User | AuthUser,
    menu_permission: str,
) -> bool:
    """Return the module-menu right, without changing unit/context rights.

    This decision is only for operation visibility. It must not be reused for
    tenant switching, unit navigation, configuration, or write permissions.
    """
    return await user_has_permission(db, user, menu_permission)


async def get_user_service_ids(db: AsyncSession, user: User | AuthUser) -> list[int]:
    if user is None:
        return []
    resolved_service_ids = cached_service_ids(user)
    if resolved_service_ids is not None:
        return sorted({int(service_id) for service_id in resolved_service_ids})

    service_ids: set[int] = set()

    res = await db.execute(
        select(user_services.c.service_id).where(user_services.c.user_id == user.id)
    )
    service_ids.update(row[0] for row in res.all())

    if user.service_id:
        service_ids.add(user.service_id)

    commission_query = (
        select(CommissionMember.service_id)
        .join(Service, Service.id == CommissionMember.service_id)
        .where(CommissionMember.user_id == user.id)
    )
    if user.organisation_id is not None:
        commission_query = commission_query.where(Service.organisation_id == user.organisation_id)

    commission_res = await db.execute(commission_query)
    service_ids.update(row[0] for row in commission_res.all())

    return sorted(service_ids)


async def user_has_permission(db: AsyncSession, user: User | AuthUser, permission_code: str) -> bool:
    resolved_permission_code = resolve_permission_code(permission_code)

    if user is None:
        return False
    role = (user.role or "").lower().replace("-", "_")
    if role in {"admin", "super_admin"}:
        return True
    resolved_permissions = cached_permission_codes(user)
    if resolved_permissions is not None:
        return resolved_permission_code in resolved_permissions
    if not user.role_id:
        return False
    perm_query = (
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
        .where(Permission.code == resolved_permission_code)
    )
    res = await db.execute(perm_query)
    return res.scalar_one_or_none() is not None


async def can_view_all_services(db: AsyncSession, user: User) -> bool:
    if await user_has_permission(db, user, "can_view_all_services"):
        return True
    if await user_has_permission(db, user, "menu_rapports"):
        return True
    if await user_has_permission(db, user, "rapports"):
        return True
    if await user_has_permission(db, user, "can_view_reports"):
        return True
    return False
