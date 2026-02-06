from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.role_menu_permission import RoleMenuPermission
from app.models.user_menu_permission import UserMenuPermission

router = APIRouter()

# Centralized list (frontend also has similar). Keep in sync.
ALL_MENUS = [
    "dashboard",
    "encaissements",
    "requisitions",
    "validation",
    "sorties_fonds",
    "rapports",
    "budget",
    "experts_comptables",
    "settings",
]


@router.get("/menu")
async def get_menu_permissions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if user.role == "admin":
        return {"is_admin": True, "menus": ALL_MENUS}

    # Read per-role permissions first.
    res = await db.execute(
        select(RoleMenuPermission.menu_name)
        .where(RoleMenuPermission.role == user.role)
        .where(RoleMenuPermission.can_access.is_(True))
    )
    menus = [row[0] for row in res.all()]

    # Auto-seed full access for role "administrateur" if not yet configured.
    if user.role == "administrateur" and not menus:
        for menu in ALL_MENUS:
            db.add(RoleMenuPermission(role=user.role, menu_name=menu, can_access=True))
        await db.commit()
        menus = list(ALL_MENUS)

    # Backward compatibility: fallback to per-user permissions if role has none.
    if not menus:
        res = await db.execute(
            select(UserMenuPermission.menu_name)
            .where(UserMenuPermission.user_id == user.id)
            .where(UserMenuPermission.can_access.is_(True))
        )
        menus = [row[0] for row in res.all()]

    # Optionally filter to known menus
    menus = [m for m in menus if m in ALL_MENUS]

    return {"is_admin": False, "menus": menus}
