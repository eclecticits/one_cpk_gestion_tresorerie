from __future__ import annotations

import uuid
from typing import Any

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.budget import BudgetLigne
from app.models.ligne_requisition import LigneRequisition
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.schemas.requisition import LigneRequisitionCreate, LigneRequisitionOut

router = APIRouter()


async def _can_force_budget_overrun(db: AsyncSession, user: User) -> bool:
    res = await db.execute(select(PrintSettings).limit(1))
    settings = res.scalar_one_or_none()
    if settings is None:
        return False
    if not settings.budget_block_overrun:
        return True
    roles = {r.strip().lower() for r in (settings.budget_force_roles or "").split(",") if r.strip()}
    return bool(user.role) and user.role.lower() in roles


def _ligne_out(l: LigneRequisition) -> LigneRequisitionOut:
    return LigneRequisitionOut(
        id=str(l.id),
        requisition_id=str(l.requisition_id),
        budget_ligne_id=l.budget_ligne_id,
        rubrique=l.rubrique,
        description=l.description,
        quantite=l.quantite,
        montant_unitaire=l.montant_unitaire or 0,
        montant_total=l.montant_total or 0,
        devise=l.devise or "USD",
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
        if item.budget_ligne_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_ligne_id manquant")
        budget_result = await db.execute(select(BudgetLigne).where(BudgetLigne.id == item.budget_ligne_id))
        budget_ligne = budget_result.scalar_one_or_none()
        if budget_ligne is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_ligne_id invalide")
        if budget_ligne.active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique budgétaire inactive")

        montant_prevu = Decimal(budget_ligne.montant_prevu or 0)
        montant_engage = Decimal(budget_ligne.montant_engage or 0)
        montant_requis = Decimal(item.montant_total or 0)
        disponible = montant_prevu - montant_engage
        if montant_requis > disponible:
            can_force = await _can_force_budget_overrun(db, user)
            if not can_force:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dépassement budgétaire: disponible {disponible}, demandé {montant_requis}",
                )

        budget_ligne.montant_engage = montant_engage + montant_requis

        ligne = LigneRequisition(
            requisition_id=rid,
            budget_ligne_id=item.budget_ligne_id,
            rubrique=item.rubrique,
            description=item.description,
            quantite=item.quantite,
            montant_unitaire=item.montant_unitaire,
            montant_total=item.montant_total,
            devise=item.devise or "USD",
        )
        lignes.append(ligne)
        db.add(ligne)
    await db.commit()
    for ligne in lignes:
        await db.refresh(ligne)
    return [_ligne_out(l) for l in lignes]
