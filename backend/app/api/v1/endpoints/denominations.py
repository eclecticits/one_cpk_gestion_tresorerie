from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import has_permission
from app.db.session import get_db
from app.models.denomination import Denomination
from app.schemas.denomination import DenominationCreate, DenominationOut, DenominationUpdate

router = APIRouter()


@router.get("", response_model=list[DenominationOut])
async def list_denominations(
    active: bool | None = Query(default=None),
    devise: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[DenominationOut]:
    stmt = select(Denomination)
    if active is True:
        stmt = stmt.where(Denomination.est_actif.is_(True))
    if devise:
        stmt = stmt.where(Denomination.devise == devise.upper())
    stmt = stmt.order_by(Denomination.devise.asc(), Denomination.ordre.asc(), Denomination.valeur.desc())
    res = await db.execute(stmt)
    return [DenominationOut.model_validate(d) for d in res.scalars().all()]


@router.post("", response_model=DenominationOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def create_denomination(
    payload: DenominationCreate,
    db: AsyncSession = Depends(get_db),
) -> DenominationOut:
    if payload.devise.upper() not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    denom = Denomination(
        devise=payload.devise.upper(),
        valeur=payload.valeur,
        label=payload.label,
        est_actif=payload.est_actif,
        ordre=payload.ordre,
    )
    db.add(denom)
    await db.commit()
    await db.refresh(denom)
    return DenominationOut.model_validate(denom)


@router.patch("/{denomination_id}", response_model=DenominationOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_denomination(
    denomination_id: int,
    payload: DenominationUpdate,
    db: AsyncSession = Depends(get_db),
) -> DenominationOut:
    res = await db.execute(select(Denomination).where(Denomination.id == denomination_id))
    denom = res.scalar_one_or_none()
    if denom is None:
        raise HTTPException(status_code=404, detail="Dénomination introuvable")

    data = payload.model_dump(exclude_unset=True)
    if "devise" in data:
        if (data["devise"] or "").upper() not in {"USD", "CDF"}:
            raise HTTPException(status_code=400, detail="devise invalide")
        denom.devise = data["devise"].upper()
    if "valeur" in data:
        denom.valeur = data["valeur"]
    if "label" in data:
        denom.label = data["label"]
    if "est_actif" in data:
        denom.est_actif = data["est_actif"]
    if "ordre" in data:
        denom.ordre = data["ordre"]

    await db.commit()
    await db.refresh(denom)
    return DenominationOut.model_validate(denom)


@router.delete("/{denomination_id}", dependencies=[Depends(has_permission("can_edit_settings"))])
async def delete_denomination(
    denomination_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Denomination).where(Denomination.id == denomination_id))
    denom = res.scalar_one_or_none()
    if denom is None:
        raise HTTPException(status_code=404, detail="Dénomination introuvable")
    await db.delete(denom)
    await db.commit()
    return {"ok": True}
