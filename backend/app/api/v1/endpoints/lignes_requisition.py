from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ligne_requisition import LigneRequisition
from app.models.user import User
from app.schemas.requisition import LigneRequisitionCreate, LigneRequisitionOut

router = APIRouter()


def _ligne_out(l: LigneRequisition) -> LigneRequisitionOut:
    return LigneRequisitionOut(
        id=str(l.id),
        requisition_id=str(l.requisition_id),
        rubrique=l.rubrique,
        description=l.description,
        quantite=l.quantite,
        montant_unitaire=l.montant_unitaire or 0,
        montant_total=l.montant_total or 0,
    )


@router.get("", response_model=list[LigneRequisitionOut])
async def list_lignes_requisition(
    requisition_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LigneRequisitionOut]:
    query = select(LigneRequisition)
    if requisition_id:
        try:
            rid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        query = query.where(LigneRequisition.requisition_id == rid)
    res = await db.execute(query)
    return [_ligne_out(l) for l in res.scalars().all()]


@router.post("", response_model=list[LigneRequisitionOut])
async def create_lignes_requisition(
    payload: list[LigneRequisitionCreate],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LigneRequisitionOut]:
    lignes: list[LigneRequisition] = []
    for item in payload:
        try:
            rid = uuid.UUID(item.requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        ligne = LigneRequisition(
            requisition_id=rid,
            rubrique=item.rubrique,
            description=item.description,
            quantite=item.quantite,
            montant_unitaire=item.montant_unitaire,
            montant_total=item.montant_total,
        )
        lignes.append(ligne)
        db.add(ligne)
    await db.commit()
    for ligne in lignes:
        await db.refresh(ligne)
    return [_ligne_out(l) for l in lignes]
