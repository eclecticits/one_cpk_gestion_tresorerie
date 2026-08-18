from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.user import User
from app.schemas.requisition import LigneRequisitionCreate, LigneRequisitionOut
from app.services.historical_snapshots import ensure_requisition_editable
from app.services.requisition_service import appliquer_reglement_requisition
from app.services.ligne_requisition_service import (
    build_ligne_requisition,
    can_force_budget_overrun,
)
from app.services.service_access import get_user_service_ids, can_view_all_services

router = APIRouter()


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
        mode_paiement=l.mode_paiement,
        compte_bancaire_id=l.compte_bancaire_id,
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
    query = select(LigneRequisition).where(LigneRequisition.organisation_id == tenant_id)
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[LigneRequisitionOut]:
    lignes: list[LigneRequisition] = []
    requisition_cache: dict[uuid.UUID, Requisition] = {}
    # Même périmètre que la création de la réquisition et que la liste des postes
    # autorisés : qui peut porter une réquisition sur un service doit pouvoir en
    # écrire les lignes. Restreindre au seul rôle "admin" produisait un 403 sur
    # un poste que le formulaire venait d'afficher comme valide.
    unrestricted = await can_view_all_services(db, user)
    force_overrun: bool | None = None
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
            req_res = await db.execute(
                select(Requisition).where(
                    Requisition.id == rid,
                    Requisition.organisation_id == tenant_id,
                    Requisition.is_deleted.is_(False),
                )
            )
            requisition = req_res.scalar_one_or_none()
            if requisition is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
            requisition_cache[rid] = requisition
        ensure_requisition_editable(requisition, attempted_fields={"lignes_requisition"})
        if not unrestricted:
            service_ids = await get_user_service_ids(db, user)
            if service_ids and requisition.service_id not in service_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation de modifier cette réquisition.",
                )
        if force_overrun is None:
            force_overrun = await can_force_budget_overrun(db, user)
        ligne = await build_ligne_requisition(
            db=db,
            requisition=requisition,
            item=item,
            tenant_id=tenant_id,
            force_overrun=force_overrun,
        )
        lignes.append(ligne)
        db.add(ligne)
    # Le mode porté par la réquisition est un résumé de ses lignes : l'ajout
    # d'une ligne d'un autre mode le fait basculer en « mixte » et impose le
    # décaissement progressif.
    if lignes:
        await db.flush()
        for requisition in requisition_cache.values():
            await appliquer_reglement_requisition(db, requisition)
    await db.commit()
    for ligne in lignes:
        await db.refresh(ligne)
    return [_ligne_out(l) for l in lignes]
