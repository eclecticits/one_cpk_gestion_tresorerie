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

from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement_tarif import EncaissementTarif, normaliser_libelle
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


async def appliquer_tarifs(
    db: AsyncSession,
    organisation_id: int,
    articles: list[dict[str, Any]],
    *,
    peut_forcer: bool,
) -> list[dict[str, Any]]:
    """Impose aux articles ce que leur tarif définit, et rend les écarts.

    Le verrou vit ici et non dans l'écran : une saisie qui contournerait le
    formulaire contournerait aussi le tarif, et deux encaissements du même
    libellé se remettraient à différer.

    Ce qui est défini s'impose, champ par champ — un tarif peut ne fixer que le
    prix, ne fixer que le poste, ou les deux. Ce qui n'est pas défini reste tel
    que la caisse l'a saisi.

    Forcer est possible, mais se sait : sans le droit d'y toucher, un écart au
    prix tarifé est refusé ; avec ce droit, il est appliqué et rendu à
    l'appelant, qui le consigne. Sans cette porte, un tarif mal réglé bloquerait
    une recette réelle jusqu'à ce qu'un administrateur le corrige.
    """
    if not articles:
        return []

    resolus = await tarifs_resolus(db, organisation_id, actifs_seulement=True)
    par_libelle = {tarif.libelle_normalise: (tarif, poste) for tarif, poste in resolus}
    if not par_libelle:
        return []

    ecarts: list[dict[str, Any]] = []
    for article in articles:
        trouve = par_libelle.get(normaliser_libelle(article.get("libelle")))
        if trouve is None:
            continue
        tarif, poste = trouve

        if tarif.montant is not None:
            tarife = Decimal(str(tarif.montant))
            saisi = Decimal(str(article.get("prix_unitaire") or 0))
            if saisi != tarife:
                if not peut_forcer:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"« {tarif.libelle} » est tarifé à {tarife} {tarif.devise} : "
                            f"montant {saisi} refusé. Corrigez le tarif dans les réglages, ou "
                            f"faites forcer le montant par un administrateur."
                        ),
                    )
                ecarts.append(
                    {
                        "libelle": tarif.libelle,
                        "champ": "prix_unitaire",
                        "tarif": str(tarife),
                        "saisi": str(saisi),
                    }
                )
            else:
                # Le prix est ferme, donc le total de la ligne l'est aussi : sans
                # ce contrôle, un prix tarifé accompagné d'un total réduit
                # laisserait passer une remise que personne n'a décidée.
                quantite = Decimal(str(article.get("quantite") or 1))
                attendu = (tarife * quantite).quantize(Decimal("0.01"))
                montant_ligne = Decimal(str(article.get("montant") or 0))
                if montant_ligne != attendu:
                    if not peut_forcer:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"« {tarif.libelle} » : {quantite} × {tarife} vaut {attendu}, "
                                f"total {montant_ligne} refusé."
                            ),
                        )
                    ecarts.append(
                        {
                            "libelle": tarif.libelle,
                            "champ": "montant",
                            "tarif": str(attendu),
                            "saisi": str(montant_ligne),
                        }
                    )

        if poste is not None:
            actuel = article.get("budget_poste_id")
            if actuel is None:
                article["budget_poste_id"] = poste.id
            elif int(actuel) != poste.id:
                if not peut_forcer:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"« {tarif.libelle} » s'impute sur {poste.code} : "
                            f"un autre poste ne peut être choisi ici."
                        ),
                    )
                ecarts.append(
                    {
                        "libelle": tarif.libelle,
                        "champ": "budget_poste_id",
                        "tarif": poste.code,
                        "saisi": str(actuel),
                    }
                )

    return ecarts
