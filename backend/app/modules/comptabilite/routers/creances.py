"""API des créances : paramétrage et reprise des notes déjà émises."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.comptabilite.models import ComptaCompte
from app.modules.comptabilite.schemas.creances import (
    CreancesParametresIn,
    CreancesParametresOut,
    EchecRepriseOut,
    RepriseCreancesIn,
    RepriseCreancesOut,
)
from app.modules.comptabilite.services.creances_service import (
    constater_notes_existantes,
    notes_sans_creance,
    regler_creances,
    societe_par_defaut,
)
from app.modules.comptabilite.services.integration_mode import get_accounting_integration_mode

router = APIRouter()

# Au-delà, la liste des refus n'apprend plus rien : ils ont presque toujours
# la même cause (un poste sans compte, un exercice absent).
ECHECS_AFFICHES = 100


async def _parametres(db: AsyncSession, tenant_id: int) -> CreancesParametresOut:
    societe = await societe_par_defaut(db, tenant_id)
    if societe is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La comptabilité n'est pas activée pour cette organisation.",
        )
    racine = (
        await db.get(ComptaCompte, societe.compte_creances_racine_id)
        if societe.compte_creances_racine_id
        else None
    )
    comptes_tiers = (
        await db.execute(
            select(func.count(ComptaCompte.id)).where(
                ComptaCompte.organisation_id == tenant_id,
                or_(ComptaCompte.tiers_expert_id.is_not(None), ComptaCompte.tiers_client_id.is_not(None)),
            )
        )
    ).scalar_one()
    return CreancesParametresOut(
        actif=societe.creances_actives,
        mode_automatique=await get_accounting_integration_mode(db, tenant_id) == "automatic",
        compte_racine_id=racine.id if racine else None,
        compte_racine_numero=racine.numero if racine else None,
        compte_racine_libelle=racine.libelle if racine else None,
        compte_racine_clients_id=societe.compte_creances_clients_racine_id,
        comptes_tiers=comptes_tiers,
        libelle_tiers=societe.libelle_tiers,
        libelle_journal=societe.libelle_journal_creances,
        notes_sans_creance=len(await notes_sans_creance(db, organisation_id=tenant_id)),
    )


@router.get(
    "/creances/parametres",
    response_model=CreancesParametresOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def get_parametres_creances(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CreancesParametresOut:
    return await _parametres(db, tenant_id)


@router.put(
    "/creances/parametres",
    response_model=CreancesParametresOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def put_parametres_creances(
    payload: CreancesParametresIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CreancesParametresOut:
    await regler_creances(
        db,
        organisation_id=tenant_id,
        actif=payload.actif,
        compte_racine_id=payload.compte_racine_id,
        compte_racine_clients_id=payload.compte_racine_clients_id,
        libelle_tiers=payload.libelle_tiers,
        libelle_journal=payload.libelle_journal,
    )
    await db.commit()
    return await _parametres(db, tenant_id)


@router.post(
    "/creances/reprise",
    response_model=RepriseCreancesOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def post_reprise_creances(
    payload: RepriseCreancesIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RepriseCreancesOut:
    """Constate la créance des notes émises avant la bascule et encore vierges."""
    rapport = await constater_notes_existantes(
        db, organisation_id=tenant_id, simulation=payload.simulation, user_id=user.id
    )
    if payload.simulation:
        await db.rollback()
    else:
        await db.commit()
    return RepriseCreancesOut(
        simulation=rapport.simulation,
        constatees=rapport.constatees,
        montant=rapport.montant,
        deja_reglees_en_partie=rapport.deja_reglees_en_partie,
        echecs=[EchecRepriseOut(numero=n, motif=m) for n, m in rapport.echecs[:ECHECS_AFFICHES]],
    )
