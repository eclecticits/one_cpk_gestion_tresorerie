"""Règles métier des lignes de réquisition.

Partagées entre la création atomique (POST /requisitions avec ses lignes) et
l'ajout de lignes sur une réquisition existante (POST /lignes-requisition) :
les deux chemins doivent appliquer exactement les mêmes contrôles budgétaires.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User

RUBRIQUES_SERVICE_OBLIGATOIRES = ("II.2.2", "II.2.3", "II.2.4", "II.2.5", "II.2.11")


async def can_force_budget_overrun(db: AsyncSession, user: User) -> bool:
    res = await db.execute(select(PrintSettings).limit(1))
    settings = res.scalar_one_or_none()
    if settings is None:
        return False
    if not settings.budget_block_overrun:
        return True
    roles = {r.strip().lower() for r in (settings.budget_force_roles or "").split(",") if r.strip()}
    return bool(user.role) and user.role.lower() in roles


async def build_ligne_requisition(
    *,
    db: AsyncSession,
    requisition: Requisition,
    item,
    tenant_id: int,
    force_overrun: bool,
) -> LigneRequisition:
    """Valide une ligne et renvoie l'objet à persister.

    Engage le montant sur le poste budgétaire. L'appelant reste responsable du
    `db.add()` et du commit : toutes les lignes d'une même réquisition doivent
    être écrites dans la même transaction que celle-ci.
    """
    if item.budget_poste_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id manquant")

    budget_result = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == item.budget_poste_id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
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
                ServiceRubrique.active.is_(True),
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
    if montant_requis > disponible and not force_overrun:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dépassement budgétaire: disponible {disponible}, demandé {montant_requis}",
        )

    budget_ligne.montant_engage = montant_engage + montant_requis

    return LigneRequisition(
        organisation_id=tenant_id,
        requisition_id=requisition.id,
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
