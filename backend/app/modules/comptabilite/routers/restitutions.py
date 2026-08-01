"""API des restitutions comptables (Lot 4).

Branchement HTTP de `reporting_service` : contrôle d'accès, résolution de
l'exercice, et conversion en schémas. Aucune logique de calcul ici.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, has_any_permission
from app.db.session import get_db
from app.modules.comptabilite.models import ComptaExercice
from app.modules.comptabilite.schemas.restitutions import (
    BalanceOut,
    EcritureJournalOut,
    GrandLivreOut,
    LigneBalanceOut,
    LivreJournalOut,
    MouvementGrandLivreOut,
)
from app.modules.comptabilite.services.reporting_service import (
    balance_generale,
    grand_livre,
    livre_journal,
)

router = APIRouter()

# La lecture des états est ouverte à tous les rôles comptables : un auditeur
# doit pouvoir consulter le Grand Livre sans pouvoir saisir.
LECTURE_COMPTA = [
    "compta.lecture", "compta.saisie", "compta.validation", "compta.cloture",
    "compta.parametrage", "compta.export",
]


async def _exercice(db: AsyncSession, tenant_id: int, exercice_id: int | None) -> ComptaExercice:
    """Exercice demandé, ou le plus récent — les écrans s'ouvrent dessus."""
    stmt = select(ComptaExercice).where(ComptaExercice.organisation_id == tenant_id)
    if exercice_id is not None:
        stmt = stmt.where(ComptaExercice.id == exercice_id)
    else:
        stmt = stmt.order_by(ComptaExercice.date_debut.desc()).limit(1)

    res = await db.execute(stmt)
    exercice = res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun exercice comptable pour cette organisation.",
        )
    return exercice


@router.get("/balance", response_model=BalanceOut, dependencies=[Depends(has_any_permission(LECTURE_COMPTA))])
async def get_balance(
    exercice_id: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BalanceOut:
    exercice = await _exercice(db, tenant_id, exercice_id)
    balance = await balance_generale(
        db,
        organisation_id=tenant_id,
        exercice_id=exercice.id,
        date_debut=date_debut,
        date_fin=date_fin,
        inclure_brouillons=inclure_brouillons,
    )
    return BalanceOut(
        exercice_id=exercice.id,
        devise_tenue=exercice.devise_tenue,
        date_debut=date_debut,
        date_fin=date_fin,
        inclure_brouillons=inclure_brouillons,
        lignes=[
            LigneBalanceOut(
                compte_id=l.compte_id,
                compte_numero=l.compte_numero,
                compte_libelle=l.compte_libelle,
                nature=l.nature,
                total_debit=l.total_debit,
                total_credit=l.total_credit,
                solde_debiteur=l.solde_debiteur,
                solde_crediteur=l.solde_crediteur,
            )
            for l in balance.lignes
        ],
        total_debit=balance.total_debit,
        total_credit=balance.total_credit,
        total_solde_debiteur=balance.total_solde_debiteur,
        total_solde_crediteur=balance.total_solde_crediteur,
        equilibree=balance.equilibree,
    )


@router.get(
    "/grand-livre", response_model=GrandLivreOut, dependencies=[Depends(has_any_permission(LECTURE_COMPTA))]
)
async def get_grand_livre(
    compte_id: int,
    exercice_id: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    curseur: str | None = None,
    limite: int = Query(default=100, ge=1, le=500),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GrandLivreOut:
    exercice = await _exercice(db, tenant_id, exercice_id)
    try:
        livre = await grand_livre(
            db,
            organisation_id=tenant_id,
            exercice_id=exercice.id,
            compte_id=compte_id,
            date_debut=date_debut,
            date_fin=date_fin,
            inclure_brouillons=inclure_brouillons,
            curseur=curseur,
            limite=limite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return GrandLivreOut(
        exercice_id=exercice.id,
        devise_tenue=exercice.devise_tenue,
        compte_id=livre.compte_id,
        compte_numero=livre.compte_numero,
        compte_libelle=livre.compte_libelle,
        date_debut=date_debut,
        date_fin=date_fin,
        inclure_brouillons=inclure_brouillons,
        solde_anterieur=livre.solde_anterieur,
        mouvements=[
            MouvementGrandLivreOut(
                ligne_id=m.ligne_id,
                ecriture_id=m.ecriture_id,
                numero=m.numero,
                date_ecriture=m.date_ecriture,
                journal_code=m.journal_code,
                libelle=m.libelle,
                reference_piece=m.reference_piece,
                debit=m.debit,
                credit=m.credit,
                statut=m.statut,
                solde_cumule=m.solde_cumule,
            )
            for m in livre.mouvements
        ],
        total_debit_page=livre.total_debit_page,
        total_credit_page=livre.total_credit_page,
        solde_final_page=livre.solde_final_page,
        curseur_suivant=livre.curseur_suivant,
    )


@router.get(
    "/journal", response_model=LivreJournalOut, dependencies=[Depends(has_any_permission(LECTURE_COMPTA))]
)
async def get_journal(
    journal_id: int,
    exercice_id: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    limite: int = Query(default=200, ge=1, le=1000),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> LivreJournalOut:
    exercice = await _exercice(db, tenant_id, exercice_id)
    try:
        journal = await livre_journal(
            db,
            organisation_id=tenant_id,
            exercice_id=exercice.id,
            journal_id=journal_id,
            date_debut=date_debut,
            date_fin=date_fin,
            inclure_brouillons=inclure_brouillons,
            limite=limite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return LivreJournalOut(
        exercice_id=exercice.id,
        devise_tenue=exercice.devise_tenue,
        journal_id=journal.journal_id,
        journal_code=journal.journal_code,
        journal_libelle=journal.journal_libelle,
        date_debut=date_debut,
        date_fin=date_fin,
        inclure_brouillons=inclure_brouillons,
        ecritures=[
            EcritureJournalOut(
                ecriture_id=e.ecriture_id,
                numero=e.numero,
                date_ecriture=e.date_ecriture,
                libelle=e.libelle,
                statut=e.statut,
                total_debit=e.total_debit,
                total_credit=e.total_credit,
            )
            for e in journal.ecritures
        ],
        total_debit=journal.total_debit,
        total_credit=journal.total_credit,
    )
