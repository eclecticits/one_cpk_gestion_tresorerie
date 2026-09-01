from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.encaissement import Encaissement
from app.models.regularisation_budgetaire import RegularisationBudgetaire
from app.models.sortie_fonds import SortieFonds
from app.services.mouvements_budgetaires import create_budget_imputation, sum_active_budget_imputations


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _to_budget_currency(montant: Decimal, devise: str, taux: object) -> Decimal:
    devise_norm = (devise or "USD").upper()
    if devise_norm == "USD":
        return _money(montant)
    rate = Decimal(str(taux or 0))
    if rate <= 0:
        raise HTTPException(status_code=400, detail=f"Taux de change requis pour régulariser un mouvement en {devise_norm}")
    return _money(Decimal(str(montant)) / rate)


async def affecter_encaissement_hors_budget(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
    lignes: list[tuple[int, Decimal]],
    justification: str,
    reference: str | None,
    idempotency_key: str,
    user_id: uuid.UUID | None,
) -> RegularisationBudgetaire:
    existing_res = await db.execute(
        select(RegularisationBudgetaire).where(
            RegularisationBudgetaire.organisation_id == organisation_id,
            RegularisationBudgetaire.idempotency_key == idempotency_key,
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing is not None:
        return existing

    enc_res = await db.execute(
        select(Encaissement)
        .where(Encaissement.id == encaissement_id, Encaissement.organisation_id == organisation_id)
        .with_for_update()
    )
    encaissement = enc_res.scalar_one_or_none()
    if encaissement is None:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    if (encaissement.statut_operation or "ACTIVE").upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="Encaissement annulé")
    if (encaissement.nature_mouvement or "").upper() != "HORS_BUDGET_A_REGULARISER":
        raise HTTPException(status_code=400, detail="Seul un encaissement hors budget peut être affecté")

    total_demande = _money(sum((Decimal(str(m)) for _pid, m in lignes), Decimal("0")))
    if total_demande <= 0:
        raise HTTPException(status_code=400, detail="Montant à affecter invalide")
    deja_impute = await sum_active_budget_imputations(db, organisation_id=organisation_id, encaissement_id=encaissement.id)
    montant_source = _money(encaissement.montant_paye or encaissement.montant_total or encaissement.montant or 0)
    reste = montant_source - deja_impute
    if total_demande > reste:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au reste à régulariser: {reste}")

    postes: list[BudgetPoste] = []
    for poste_id, _montant in lignes:
        poste_res = await db.execute(
            select(BudgetPoste)
            .where(BudgetPoste.id == poste_id, BudgetPoste.organisation_id == organisation_id, BudgetPoste.is_deleted.is_(False))
            .with_for_update()
        )
        poste = poste_res.scalar_one_or_none()
        if poste is None or (poste.type or "").upper() != "RECETTE":
            raise HTTPException(status_code=400, detail=f"Poste recette invalide: {poste_id}")
        postes.append(poste)

    devise = (encaissement.devise_perception or "USD").upper()
    taux = encaissement.taux_change_applique
    total_budget = _money(sum((_to_budget_currency(Decimal(str(m)), devise, taux) for _pid, m in lignes), Decimal("0")))
    regularisation = RegularisationBudgetaire(
        organisation_id=organisation_id,
        encaissement_id=encaissement.id,
        ancien_nature_mouvement=encaissement.nature_mouvement,
        nouveau_nature_mouvement="BUDGETAIRE",
        montant_mouvement=total_demande,
        devise_mouvement=devise,
        montant_budget=total_budget,
        exchange_rate_snapshot=taux,
        justification=justification,
        reference=(reference or "").strip() or None,
        idempotency_key=idempotency_key,
        created_by=user_id,
    )
    db.add(regularisation)
    await db.flush()

    by_id = {poste.id: poste for poste in postes}
    for poste_id, montant in lignes:
        montant_clean = _money(montant)
        poste = by_id[poste_id]
        montant_budget = _to_budget_currency(montant_clean, devise, taux)
        await create_budget_imputation(
            db,
            organisation_id=organisation_id,
            encaissement_id=encaissement.id,
            regularisation_budgetaire_id=regularisation.id,
            budget_poste_id=poste_id,
            sens="RECETTE_REALISEE",
            montant_mouvement=montant_clean,
            devise_mouvement=devise,
            montant_budget=montant_budget,
            exchange_rate_snapshot=taux,
            created_by=user_id,
        )
        poste.montant_paye = _money((poste.montant_paye or 0) + montant_budget)

    reste_apres = reste - total_demande
    if reste_apres > 0:
        encaissement.hors_budget_status = "PARTIELLEMENT_AFFECTE"
    else:
        encaissement.nature_mouvement = "BUDGETAIRE"
        encaissement.impact_budgetaire = True
        encaissement.hors_budget_status = "AFFECTE_BUDGET"
        if len(lignes) == 1:
            encaissement.budget_poste_id = lignes[0][0]
    await db.flush()
    return regularisation


async def affecter_sortie_hors_budget(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie_fonds_id: uuid.UUID,
    lignes: list[tuple[int, Decimal]],
    justification: str,
    reference: str | None,
    idempotency_key: str,
    user_id: uuid.UUID | None,
    autoriser_depassement: bool = False,
) -> RegularisationBudgetaire:
    """Pendant dépense de `affecter_encaissement_hors_budget`.

    Une sortie payée hors budget reste une sortie payée : la trésorerie a déjà
    bougé. Régulariser ne rejoue pas le décaissement, cela impute a posteriori
    le montant sur un ou plusieurs postes de dépense.
    """
    existing_res = await db.execute(
        select(RegularisationBudgetaire).where(
            RegularisationBudgetaire.organisation_id == organisation_id,
            RegularisationBudgetaire.idempotency_key == idempotency_key,
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing is not None:
        return existing

    sortie_res = await db.execute(
        select(SortieFonds)
        .where(SortieFonds.id == sortie_fonds_id, SortieFonds.organisation_id == organisation_id)
        .with_for_update()
    )
    sortie = sortie_res.scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=404, detail="Sortie de fonds introuvable")
    if (sortie.statut or "VALIDE").upper() != "VALIDE":
        raise HTTPException(status_code=400, detail="Sortie annulée")
    if (sortie.nature_mouvement or "").upper() != "HORS_BUDGET_A_REGULARISER":
        raise HTTPException(status_code=400, detail="Seule une sortie hors budget peut être affectée")

    total_demande = _money(sum((Decimal(str(m)) for _pid, m in lignes), Decimal("0")))
    if total_demande <= 0:
        raise HTTPException(status_code=400, detail="Montant à affecter invalide")
    deja_impute = await sum_active_budget_imputations(db, organisation_id=organisation_id, sortie_fonds_id=sortie.id)
    montant_source = _money(sortie.montant_paye or 0)
    reste = montant_source - deja_impute
    if total_demande > reste:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au reste à régulariser: {reste}")

    devise = (sortie.devise or "USD").upper()
    taux = sortie.exchange_rate_snapshot

    postes: dict[int, BudgetPoste] = {}
    for poste_id, _montant in lignes:
        if poste_id in postes:
            continue
        poste_res = await db.execute(
            select(BudgetPoste)
            .where(BudgetPoste.id == poste_id, BudgetPoste.organisation_id == organisation_id, BudgetPoste.is_deleted.is_(False))
            .with_for_update()
        )
        poste = poste_res.scalar_one_or_none()
        if poste is None or (poste.type or "").upper() != "DEPENSE":
            raise HTTPException(status_code=400, detail=f"Poste dépense invalide: {poste_id}")
        postes[poste_id] = poste

    total_budget = _money(sum((_to_budget_currency(Decimal(str(m)), devise, taux) for _pid, m in lignes), Decimal("0")))
    regularisation = RegularisationBudgetaire(
        organisation_id=organisation_id,
        sortie_fonds_id=sortie.id,
        ancien_nature_mouvement=sortie.nature_mouvement,
        nouveau_nature_mouvement="BUDGETAIRE",
        montant_mouvement=total_demande,
        devise_mouvement=devise,
        montant_budget=total_budget,
        exchange_rate_snapshot=taux,
        justification=justification,
        reference=(reference or "").strip() or None,
        idempotency_key=idempotency_key,
        created_by=user_id,
    )
    db.add(regularisation)
    await db.flush()

    for poste_id, montant in lignes:
        montant_clean = _money(montant)
        poste = postes[poste_id]
        montant_budget = _to_budget_currency(montant_clean, devise, taux)
        nouveau_cumul = _money((poste.montant_paye or 0) + montant_budget)
        if not autoriser_depassement and nouveau_cumul > _money(poste.montant_prevu or 0):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Dépassement budgétaire (poste {poste.code}): plafond {poste.montant_prevu}, "
                    f"déjà payé {poste.montant_paye}, demandé {montant_budget}"
                ),
            )
        await create_budget_imputation(
            db,
            organisation_id=organisation_id,
            sortie_fonds_id=sortie.id,
            regularisation_budgetaire_id=regularisation.id,
            budget_poste_id=poste_id,
            sens="DEPENSE_PAYEE",
            montant_mouvement=montant_clean,
            devise_mouvement=devise,
            montant_budget=montant_budget,
            exchange_rate_snapshot=taux,
            created_by=user_id,
        )
        poste.montant_paye = nouveau_cumul

    reste_apres = reste - total_demande
    if reste_apres > 0:
        sortie.hors_budget_status = "PARTIELLEMENT_AFFECTE"
    else:
        sortie.nature_mouvement = "BUDGETAIRE"
        sortie.impact_budgetaire = True
        sortie.hors_budget_status = "AFFECTE_BUDGET"
        if len({pid for pid, _ in lignes}) == 1:
            sortie.budget_poste_id = lignes[0][0]
    await db.flush()
    return regularisation
