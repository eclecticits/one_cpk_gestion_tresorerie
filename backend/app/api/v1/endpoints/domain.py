from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.rubrique import Rubrique
from app.models.user import User
from app.schemas.admin import RubriqueOut

router = APIRouter()

def _rubrique_out(r: Rubrique) -> RubriqueOut:
    return RubriqueOut(
        id=str(r.id),
        code=r.code,
        libelle=r.libelle,
        description=r.description,
        active=r.active,
    )


def _parse_rubrique_order(order: str | None):
    if not order:
        return Rubrique.libelle.asc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "libelle": Rubrique.libelle,
        "code": Rubrique.code,
        "created_at": Rubrique.created_at,
        "active": Rubrique.active,
    }
    col = column_map.get(field)
    if col is None:
        return Rubrique.libelle.asc()
    return col.desc() if direction.lower() == "desc" else col.asc()


@router.get("/rubriques", response_model=list[RubriqueOut])
async def list_rubriques(
    active: bool | None = Query(default=None),
    order: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RubriqueOut]:
    stmt = select(Rubrique)
    if active is not None:
        stmt = stmt.where(Rubrique.active == active)
    stmt = stmt.order_by(_parse_rubrique_order(order))
    res = await db.execute(stmt)
    return [_rubrique_out(r) for r in res.scalars().all()]

@router.get("/users")
def list_users():
    return {"message": "Liste des utilisateurs"}

@router.get("/paiements")
def list_paiements():
    return {"message": "Liste des paiements"}
