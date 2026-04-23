from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.permissions import ALL_MENUS, MODULE_PERMISSION_MAP
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions
from app.services.service_access import get_user_service_ids

router = APIRouter()


@router.get("/menu")
async def get_menu_permissions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return {"is_admin": True, "menus": ALL_MENUS}

    menus: set[str] = set()

    perm_codes: set[str] = set()

    # Derive menus from RBAC permissions
    if user.role_id:
        perm_res = await db.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == user.role_id)
        )
        perm_codes = {row[0] for row in perm_res.all()}

        for menu_code, permission_code in MODULE_PERMISSION_MAP.items():
            if permission_code in perm_codes:
                menus.add(menu_code)

    service_ids = await get_user_service_ids(db, user)
    if service_ids:
        menus.add("services")

    filtered = [m for m in menus if m in ALL_MENUS]
    return {"is_admin": False, "menus": filtered}
