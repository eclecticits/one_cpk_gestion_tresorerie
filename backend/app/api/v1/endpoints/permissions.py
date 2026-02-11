from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.rbac import Permission, role_permissions

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

    menus: set[str] = {"dashboard"}

    # Derive menus from RBAC permissions
    if user.role_id:
        perm_res = await db.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == user.role_id)
        )
        perm_codes = {row[0] for row in perm_res.all()}

        if perm_codes.intersection({"can_create_requisition", "can_verify_technical", "can_validate_final"}):
            menus.add("requisitions")
            menus.add("validation")
        if "can_execute_payment" in perm_codes:
            menus.add("sorties_fonds")
        if "can_view_reports" in perm_codes:
            menus.update({"rapports", "encaissements", "budget", "experts_comptables"})
        if perm_codes.intersection({"can_manage_users", "can_edit_settings"}):
            menus.add("settings")

    filtered = [m for m in menus if m in ALL_MENUS]
    return {"is_admin": False, "menus": filtered}
