from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import codes_explicites_accordes, get_current_user
from app.core.permissions import ALL_MENUS, MODULE_PERMISSION_MAP, PERMISSIONS_EXPLICITES
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions
from app.services.service_access import get_user_service_ids

router = APIRouter()


@router.get("/menu")
async def get_menu_permissions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    # `explicit_permissions` : codes que `is_admin` n'ouvre pas d'office (cf.
    # PERMISSIONS_EXPLICITES) — l'interface ne les accorde que s'ils figurent
    # dans `permissions`.
    explicites = sorted(PERMISSIONS_EXPLICITES)
    role = (user.role or "").lower()
    if role in {"admin", "super_admin"}:
        perm_res = await db.execute(select(Permission.code).order_by(Permission.code.asc()))
        codes = [row[0] for row in perm_res.all()]
        if role == "admin":
            accordes = await codes_explicites_accordes(db, user)
            codes = [code for code in codes if code not in PERMISSIONS_EXPLICITES or code in accordes]
        return {"is_admin": True, "menus": ALL_MENUS, "permissions": codes, "explicit_permissions": explicites}

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
    return {
        "is_admin": False,
        "menus": filtered,
        "permissions": sorted(perm_codes),
        "explicit_permissions": explicites,
    }
