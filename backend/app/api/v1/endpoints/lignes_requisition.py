from __future__ import annotations

import uuid
from typing import Any

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.requisition import LigneRequisitionCreate, LigneRequisitionOut
from app.services.service_access import get_user_service_ids, can_view_all_services

router = APIRouter()

RUBRIQUES_SERVICE_OBLIGATOIRES = ("II.2.2", "II.2.3", "II.2.4", "II.2.5", "II.2.11")


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
        budget_poste_id=l.budget_poste_id,
        rubrique=l.rubrique,
        description=l.description,
        quantite=l.quantite,
        montant_unitaire=l.montant_unitaire or 0,
        montant_total=l.montant_total or 0,
        devise=l.devise or "USD",
        budget_poste_code_snapshot=l.budget_poste_code_snapshot,
        budget_poste_libelle_snapshot=l.budget_poste_libelle_snapshot,
        montant_alloue_snapshot=l.montant_alloue_snapshot,
        montant_disponible_snapshot=l.montant_disponible_snapshot,
    )


@router.get("", response_model=list[LigneRequisitionOut])
async def list_lignes_requisition(
    requisition_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[LigneRequisitionOut]:
    query = select(LigneRequisition)
    if requisition_id:
        try:
            rid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        query = query.where(LigneRequisition.requisition_id == rid)
        req_res = await db.execute(
            select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
        )
        requisition = req_res.scalar_one_or_none()
        if requisition is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        if not await can_view_all_services(db, user):
            service_ids = await get_user_service_ids(db, user)
            if service_ids and requisition.service_id not in service_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation de consulter cette réquisition.",
                )
    elif not await can_view_all_services(db, user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="requisition_id requis")
    res = await db.execute(query)
    lignes = res.scalars().all()
    missing_ids = {
        l.budget_poste_id
        for l in lignes
        if (not (l.rubrique or "").strip()) and l.budget_poste_id is not None
    }
    budget_map: dict[int, BudgetPoste] = {}
    if missing_ids:
        budget_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id.in_(list(missing_ids))))
        budget_map = {b.id: b for b in budget_res.scalars().all()}

    outputs: list[LigneRequisitionOut] = []
    for l in lignes:
        rubrique_value = (l.rubrique or "").strip()
        if not rubrique_value and l.budget_poste_id is not None:
            budget_line = budget_map.get(l.budget_poste_id)
            if budget_line:
                if budget_line.code and budget_line.libelle:
                    rubrique_value = f"{budget_line.code} - {budget_line.libelle}"
                else:
                    rubrique_value = budget_line.code or budget_line.libelle or ""
        outputs.append(
            LigneRequisitionOut(
                id=str(l.id),
                requisition_id=str(l.requisition_id),
                budget_poste_id=l.budget_poste_id,
                rubrique=rubrique_value,
                description=l.description,
                quantite=l.quantite,
                montant_unitaire=l.montant_unitaire or 0,
                montant_total=l.montant_total or 0,
                devise=l.devise or "USD",
                budget_poste_code_snapshot=l.budget_poste_code_snapshot,
                budget_poste_libelle_snapshot=l.budget_poste_libelle_snapshot,
                montant_alloue_snapshot=l.montant_alloue_snapshot,
                montant_disponible_snapshot=l.montant_disponible_snapshot,
            )
        )
    return outputs


@router.post("", response_model=list[LigneRequisitionOut])
async def create_lignes_requisition(
    payload: list[LigneRequisitionCreate],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LigneRequisitionOut]:
    lignes: list[LigneRequisition] = []
    requisition_cache: dict[uuid.UUID, Requisition] = {}
    for item in payload:
        if isinstance(item.requisition_id, uuid.UUID):
            rid = item.requisition_id
        else:
            try:
                rid = uuid.UUID(item.requisition_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        requisition = requisition_cache.get(rid)
        if requisition is None:
            req_res = await db.execute(select(Requisition).where(Requisition.id == rid))
            requisition = req_res.scalar_one_or_none()
            if requisition is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
            requisition_cache[rid] = requisition
        if user.role != "admin":
            service_ids = await get_user_service_ids(db, user)
            if service_ids and requisition.service_id not in service_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation de modifier cette réquisition.",
                )
        if item.budget_poste_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id manquant")
        budget_result = await db.execute(select(BudgetPoste).where(BudgetPoste.id == item.budget_poste_id))
        budget_ligne = budget_result.scalar_one_or_none()
        if budget_ligne is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id invalide")
        if budget_ligne.active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique budgétaire inactive")
        if requisition.service_id:
            allowed_res = await db.execute(
                select(ServiceRubrique.id).where(
                    ServiceRubrique.service_id == requisition.service_id,
                    ServiceRubrique.budget_poste_id == budget_ligne.id,
                )
            )
            if allowed_res.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation d'utiliser cette rubrique budgétaire.",
                )

        if budget_ligne.code and any(
            budget_ligne.code.startswith(prefix) for prefix in RUBRIQUES_SERVICE_OBLIGATOIRES
        ):
            if not requisition.service_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Le service est obligatoire pour la rubrique {budget_ligne.code}",
                )

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
            budget_poste_id=item.budget_poste_id,
            rubrique=item.rubrique,
            description=item.description,
            quantite=item.quantite,
            montant_unitaire=item.montant_unitaire,
            montant_total=item.montant_total,
            devise=item.devise or "USD",
            budget_poste_code_snapshot=budget_ligne.code,
            budget_poste_libelle_snapshot=budget_ligne.libelle,
            montant_alloue_snapshot=montant_prevu,
            montant_disponible_snapshot=disponible,
        )
        lignes.append(ligne)
        db.add(ligne)
    await db.commit()
    for ligne in lignes:
        await db.refresh(ligne)
    return [_ligne_out(l) for l in lignes]
