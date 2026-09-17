"""Résolution des tarifs d'encaissement vers l'exercice budgétaire courant.

Un tarif désigne son poste par un code (« II.1.1.2 »), pas par un identifiant :
un poste appartient à un exercice, et son identifiant change d'une année à
l'autre. Le code se résout ici, au moment de s'en servir — l'ouverture d'un
exercice ne demande donc pas de repointer les tarifs.

Un code qui ne désigne aucun poste de recette actif de l'exercice courant ne
vaut pas imputation : la résolution rend `None`, et l'appelant le dit plutôt
que d'imputer au hasard.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement_tarif import EncaissementTarif
from app.models.print_settings import PrintSettings


async def exercice_courant(db: AsyncSession, organisation_id: int) -> BudgetExercice | None:
    """L'exercice sur lequel travaille l'organisation.

    Même règle que l'écran Budget (`endpoints/budget.py`) : l'exercice des
    réglages s'il existe, sinon le plus récent non clôturé, sinon le plus
    récent. Deux règles divergentes feraient qu'un tarif viserait un exercice
    et l'encaissement un autre.
    """
    settings = (
        await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1))
    ).scalar_one_or_none()
    if settings and settings.fiscal_year:
        exercice = (
            await db.execute(
                select(BudgetExercice).where(
                    BudgetExercice.organisation_id == organisation_id,
                    BudgetExercice.annee == settings.fiscal_year,
                )
            )
        ).scalar_one_or_none()
        if exercice:
            return exercice

    actif = (
        await db.execute(
            select(BudgetExercice)
            .where(
                BudgetExercice.organisation_id == organisation_id,
                BudgetExercice.statut != StatutBudget.CLOTURE,
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if actif:
        return actif

    return (
        await db.execute(
            select(BudgetExercice)
            .where(BudgetExercice.organisation_id == organisation_id)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def postes_par_code(
    db: AsyncSession, organisation_id: int, codes: list[str]
) -> dict[str, BudgetPoste]:
    """Postes de RECETTE actifs de l'exercice courant, par code normalisé.

    Un encaissement alimente une recette : un tarif qui pointerait une dépense
    n'est pas résolu, et l'écran le signale comme un code introuvable.
    """
    cherches = {code.strip().upper() for code in codes if (code or "").strip()}
    if not cherches:
        return {}
    exercice = await exercice_courant(db, organisation_id)
    if exercice is None:
        return {}
    postes = (
        await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.organisation_id == organisation_id,
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.active.is_(True),
                func.upper(BudgetPoste.type) == "RECETTE",
                func.upper(BudgetPoste.code).in_(cherches),
            )
        )
    ).scalars().all()
    return {(poste.code or "").strip().upper(): poste for poste in postes}


async def tarifs_resolus(
    db: AsyncSession, organisation_id: int, *, actifs_seulement: bool = False
) -> list[tuple[EncaissementTarif, BudgetPoste | None]]:
    """Les tarifs de l'organisation, chacun avec le poste où il tombe aujourd'hui."""
    requete = select(EncaissementTarif).where(EncaissementTarif.organisation_id == organisation_id)
    if actifs_seulement:
        requete = requete.where(EncaissementTarif.is_active.is_(True))
    tarifs = list(
        (
            await db.execute(requete.order_by(EncaissementTarif.position, EncaissementTarif.id))
        ).scalars().all()
    )
    postes = await postes_par_code(
        db, organisation_id, [t.budget_poste_code for t in tarifs if t.budget_poste_code]
    )
    return [
        (tarif, postes.get((tarif.budget_poste_code or "").strip().upper()) if tarif.budget_poste_code else None)
        for tarif in tarifs
    ]
