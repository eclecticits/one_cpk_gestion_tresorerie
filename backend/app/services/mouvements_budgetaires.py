from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.mouvement_budget_imputation import MouvementBudgetImputation


NatureMouvement = Literal[
    "BUDGETAIRE",
    "HORS_BUDGET_A_REGULARISER",
    "FONDS_DE_TIERS",
    "TRANSFERT_INTERNE",
]

HORS_BUDGET_STATUSES = {
    "A_REGULARISER",
    "PARTIELLEMENT_AFFECTE",
    "AFFECTE_BUDGET",
    "MAINTENU_HORS_BUDGET",
    "ANNULE",
}

BUDGET_IMPACT_BY_NATURE: dict[str, bool] = {
    "BUDGETAIRE": True,
    "HORS_BUDGET_A_REGULARISER": False,
    "FONDS_DE_TIERS": False,
    "TRANSFERT_INTERNE": False,
}


def normalize_nature(value: str | None, *, default: NatureMouvement = "BUDGETAIRE") -> NatureMouvement:
    nature = (value or default).strip().upper()
    if nature not in BUDGET_IMPACT_BY_NATURE:
        raise HTTPException(status_code=400, detail="nature_mouvement invalide")
    return nature  # type: ignore[return-value]


def impact_for_nature(nature: str | None) -> bool:
    return BUDGET_IMPACT_BY_NATURE[normalize_nature(nature)]


def hors_budget_initial_status(nature: str) -> str | None:
    if nature == "HORS_BUDGET_A_REGULARISER":
        return "A_REGULARISER"
    return None


async def create_budget_imputation(
    db: AsyncSession,
    *,
    organisation_id: int,
    budget_poste_id: int,
    sens: Literal["RECETTE_REALISEE", "DEPENSE_PAYEE", "RETOUR_DEPENSE"],
    montant_mouvement: Decimal,
    devise_mouvement: str,
    montant_budget: Decimal,
    created_by: uuid.UUID | None,
    encaissement_id: uuid.UUID | None = None,
    payment_history_id: uuid.UUID | None = None,
    sortie_fonds_id: uuid.UUID | None = None,
    retour_caisse_id: uuid.UUID | None = None,
    regularisation_budgetaire_id: uuid.UUID | None = None,
    exchange_rate_snapshot: Decimal | None = None,
) -> MouvementBudgetImputation:
    if sum(1 for value in (encaissement_id, payment_history_id, sortie_fonds_id, retour_caisse_id) if value is not None) != 1:
        raise HTTPException(status_code=400, detail="Une imputation doit référencer exactement une source")
    if montant_mouvement <= 0:
        raise HTTPException(status_code=400, detail="Montant d'imputation invalide")
    if montant_budget < 0:
        raise HTTPException(status_code=400, detail="Montant budgétaire invalide")

    poste_res = await db.execute(
        select(BudgetPoste)
        .where(BudgetPoste.id == budget_poste_id, BudgetPoste.organisation_id == organisation_id)
        .with_for_update()
    )
    poste = poste_res.scalar_one_or_none()
    if poste is None:
        raise HTTPException(status_code=400, detail="Poste budgétaire introuvable")

    imputation = MouvementBudgetImputation(
        organisation_id=organisation_id,
        encaissement_id=encaissement_id,
        payment_history_id=payment_history_id,
        sortie_fonds_id=sortie_fonds_id,
        retour_caisse_id=retour_caisse_id,
        regularisation_budgetaire_id=regularisation_budgetaire_id,
        budget_poste_id=budget_poste_id,
        sens=sens,
        montant_mouvement=montant_mouvement,
        devise_mouvement=(devise_mouvement or "USD").upper(),
        montant_budget=montant_budget,
        exchange_rate_snapshot=exchange_rate_snapshot,
        statut="ACTIVE",
        created_by=created_by,
    )
    db.add(imputation)
    await db.flush()
    return imputation


async def active_imputations_for_source(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID | None = None,
    payment_history_id: uuid.UUID | None = None,
    sortie_fonds_id: uuid.UUID | None = None,
    retour_caisse_id: uuid.UUID | None = None,
) -> list[MouvementBudgetImputation]:
    if sum(1 for value in (encaissement_id, payment_history_id, sortie_fonds_id, retour_caisse_id) if value is not None) != 1:
        raise HTTPException(status_code=400, detail="Source d'imputation ambiguë")
    conditions = [MouvementBudgetImputation.organisation_id == organisation_id, MouvementBudgetImputation.statut == "ACTIVE"]
    if encaissement_id is not None:
        conditions.append(MouvementBudgetImputation.encaissement_id == encaissement_id)
    if payment_history_id is not None:
        conditions.append(MouvementBudgetImputation.payment_history_id == payment_history_id)
    if sortie_fonds_id is not None:
        conditions.append(MouvementBudgetImputation.sortie_fonds_id == sortie_fonds_id)
    if retour_caisse_id is not None:
        conditions.append(MouvementBudgetImputation.retour_caisse_id == retour_caisse_id)
    res = await db.execute(select(MouvementBudgetImputation).where(*conditions).with_for_update())
    return list(res.scalars().all())


async def cancel_budget_imputations(
    db: AsyncSession,
    *,
    organisation_id: int,
    user_id: uuid.UUID | None,
    encaissement_id: uuid.UUID | None = None,
    payment_history_id: uuid.UUID | None = None,
    sortie_fonds_id: uuid.UUID | None = None,
    retour_caisse_id: uuid.UUID | None = None,
) -> bool:
    imputations = await active_imputations_for_source(
        db,
        organisation_id=organisation_id,
        encaissement_id=encaissement_id,
        payment_history_id=payment_history_id,
        sortie_fonds_id=sortie_fonds_id,
        retour_caisse_id=retour_caisse_id,
    )
    if not imputations:
        return False
    now = datetime.now(timezone.utc)
    poste_ids = {imp.budget_poste_id for imp in imputations}
    postes_res = await db.execute(
        select(BudgetPoste)
        .where(BudgetPoste.organisation_id == organisation_id, BudgetPoste.id.in_(poste_ids))
        .with_for_update()
    )
    postes = {poste.id: poste for poste in postes_res.scalars().all()}
    for imp in imputations:
        poste = postes.get(imp.budget_poste_id)
        if poste is None:
            raise HTTPException(status_code=400, detail="Poste budgétaire d'imputation introuvable")
        if imp.sens in {"RECETTE_REALISEE", "DEPENSE_PAYEE"}:
            poste.montant_paye = max(Decimal("0"), Decimal(str(poste.montant_paye or 0)) - Decimal(str(imp.montant_budget or 0)))
        elif imp.sens == "RETOUR_DEPENSE":
            poste.montant_paye = Decimal(str(poste.montant_paye or 0)) + Decimal(str(imp.montant_budget or 0))
        imp.statut = "ANNULEE"
        imp.annulee_le = now
        imp.annulee_par_id = user_id
    await db.flush()
    return True


async def sum_active_budget_imputations(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID | None = None,
    sortie_fonds_id: uuid.UUID | None = None,
) -> Decimal:
    if sum(1 for value in (encaissement_id, sortie_fonds_id) if value is not None) != 1:
        # Sans filtre de source on totaliserait tout l'exercice de l'organisation :
        # une erreur d'appel doit échouer, pas renvoyer un cumul faux.
        raise HTTPException(status_code=400, detail="Source d'imputation ambiguë")
    conditions = [MouvementBudgetImputation.organisation_id == organisation_id, MouvementBudgetImputation.statut == "ACTIVE"]
    if encaissement_id is not None:
        conditions.append(MouvementBudgetImputation.encaissement_id == encaissement_id)
    if sortie_fonds_id is not None:
        conditions.append(MouvementBudgetImputation.sortie_fonds_id == sortie_fonds_id)
    res = await db.execute(select(func.coalesce(func.sum(MouvementBudgetImputation.montant_mouvement), 0)).where(*conditions))
    return Decimal(str(res.scalar_one() or 0))


async def sum_active_by_encaissement(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    """Montant déjà imputé au budget, par encaissement, en une seule requête.

    Sert à afficher le reste à régulariser d'un mouvement hors budget sans
    interroger la base une fois par ligne de liste.
    """
    if not encaissement_ids:
        return {}
    res = await db.execute(
        select(
            MouvementBudgetImputation.encaissement_id,
            func.coalesce(func.sum(MouvementBudgetImputation.montant_mouvement), 0),
        )
        .where(
            MouvementBudgetImputation.organisation_id == organisation_id,
            MouvementBudgetImputation.statut == "ACTIVE",
            MouvementBudgetImputation.encaissement_id.in_(encaissement_ids),
        )
        .group_by(MouvementBudgetImputation.encaissement_id)
    )
    return {row[0]: Decimal(str(row[1] or 0)) for row in res.all()}


async def sum_active_by_sortie(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    """Pendant dépense de `sum_active_by_encaissement`."""
    if not sortie_ids:
        return {}
    res = await db.execute(
        select(
            MouvementBudgetImputation.sortie_fonds_id,
            func.coalesce(func.sum(MouvementBudgetImputation.montant_mouvement), 0),
        )
        .where(
            MouvementBudgetImputation.organisation_id == organisation_id,
            MouvementBudgetImputation.statut == "ACTIVE",
            MouvementBudgetImputation.sortie_fonds_id.in_(sortie_ids),
        )
        .group_by(MouvementBudgetImputation.sortie_fonds_id)
    )
    return {row[0]: Decimal(str(row[1] or 0)) for row in res.all()}
