from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.projet_activite import ProjetActivite
from app.schemas.projet_activite import ProjetActiviteCreate, ProjetActiviteResponse, ProjetActiviteUpdate

router = APIRouter(prefix="/projets-activites")


@router.get("", response_model=list[ProjetActiviteResponse])
async def list_projets_activites(
    active: bool | None = Query(default=None),
    type: str | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ProjetActivite).where(ProjetActivite.organisation_id == tenant_id)
    if active is not None:
        stmt = stmt.where(ProjetActivite.is_active.is_(active))
    if type:
        stmt = stmt.where(ProjetActivite.type == type.upper())
    stmt = stmt.order_by(ProjetActivite.type, func.lower(ProjetActivite.libelle))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ProjetActiviteResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("can_edit_settings"))])
async def create_projet_activite(
    payload: ProjetActiviteCreate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    code = payload.code.strip().upper()
    libelle = payload.libelle.strip()
    duplicate = await db.scalar(
        select(ProjetActivite).where(
            ProjetActivite.organisation_id == tenant_id,
            func.upper(ProjetActivite.code) == code,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Ce code projet/activité existe déjà.")
    item = ProjetActivite(
        organisation_id=tenant_id,
        code=code,
        libelle=libelle,
        type=payload.type.upper(),
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ProjetActiviteResponse, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_projet_activite(
    item_id: int,
    payload: ProjetActiviteUpdate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(select(ProjetActivite).where(ProjetActivite.id == item_id, ProjetActivite.organisation_id == tenant_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Projet ou activité introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        code = data["code"].strip().upper()
        duplicate = await db.scalar(
            select(ProjetActivite).where(
                ProjetActivite.organisation_id == tenant_id,
                func.upper(ProjetActivite.code) == code,
                ProjetActivite.id != item_id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Ce code projet/activité existe déjà.")
        data["code"] = code
    if "libelle" in data and data["libelle"] is not None:
        data["libelle"] = data["libelle"].strip()
    if "type" in data and data["type"] is not None:
        data["type"] = data["type"].upper()
    for key, value in data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item
