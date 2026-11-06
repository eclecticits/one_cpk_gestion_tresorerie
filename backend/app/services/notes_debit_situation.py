"""Situation des membres : ce que chacun doit, colonne par colonne.

Partagé par l'onglet « Situation des membres » des notes de débit et par le
Tableau, qui y lit si la cotisation est réglée. Le calcul ne lit que les
notes qu'on lui passe : à l'appelant de décider lesquelles il a le droit de voir.

Les articles portent la nature et l'exercice réels. Un versement partiel d'une
note s'impute d'abord sur la dette la plus ancienne ; le surplus devient une
avance N+1, jamais un reste négatif. Une créance sans nature se range par son
poste, selon les « Paramètres notes de débit ».
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.domain.notes_debit import (
    ARRIERE_AUTRE_PENALITE,
    ARRIERE_COTISATION,
    ARRIERE_PENALITE_APO,
    AUTRE_PENALITE,
    COTISATION_ANNUELLE,
    LEGACY,
    PENALITE_APO,
    libelle_categorie,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.expert_comptable import ExpertComptable
from app.services.notes_debit_rattachements import Classeur, categorie_membre, classeur, colonne_situation

COLONNES_SITUATION = (
    "cotisations_anterieures",
    "penalites_anterieures",
    "cotisation_n",
    "penalites_n",
    "autres_creances",
)


def argent(valeur: Decimal) -> str:
    return str(valeur.quantize(Decimal("0.01")))


def calculer_situation(
    lignes: list[tuple[Any, Any]],
    articles: dict[uuid.UUID, list[dict[str, Any]]],
    rattachements: Classeur,
    annee: int,
) -> dict[uuid.UUID, dict[str, Any]]:
    """Un groupe par expert : montants par colonne, règlements, reste, avance.

    `lignes` : (note, expert) ; `articles` : les articles de chaque note, tels
    que `_articles_par_note` les donne.
    """
    zero = Decimal("0.00")
    categories_cotisation = {COTISATION_ANNUELLE, ARRIERE_COTISATION}
    categories_penalite = {
        PENALITE_APO,
        ARRIERE_PENALITE_APO,
        AUTRE_PENALITE,
        ARRIERE_AUTRE_PENALITE,
    }

    groupes: dict[uuid.UUID, dict[str, Any]] = {}
    for note, expert in lignes:
        groupe = groupes.setdefault(
            expert.id,
            {
                "expert": {
                    "id": str(expert.id),
                    "numero_ordre": expert.numero_ordre,
                    "nom": expert.nom_denomination,
                    "type_ec": expert.type_ec,
                    "statut_professionnel": expert.statut_professionnel,
                },
                "type_client": note.type_client,
                "cotisations_anterieures": zero,
                "penalites_anterieures": zero,
                "cotisation_n": zero,
                "penalites_n": zero,
                "autres_creances": zero,
                "total_creances": zero,
                "reglements": zero,
                "reste_du": zero,
                "avance_n_plus_1": zero,
                "nb_notes": 0,
                # Ce qui reste dû colonne par colonne, après imputation sur la
                # dette la plus ancienne : le Tableau y lit la cotisation.
                "restes": dict.fromkeys(COLONNES_SITUATION, zero),
                "autres_details": [],
            },
        )
        groupe["nb_notes"] += 1
        total_note = max(Decimal(note.montant_total or 0), zero)
        paye_note = max(Decimal(note.montant_paye or 0), zero)
        a_imputer = min(total_note, paye_note)
        groupe["avance_n_plus_1"] += max(paye_note - total_note, zero)
        exercice_note = note.exercice or (note.date_encaissement.year if note.date_encaissement else annee)

        lignes_note = articles.get(note.id, [])
        if not lignes_note:
            lignes_note = [
                {
                    "categorie": LEGACY,
                    "libelle": note.libelle or "Créance historique non ventilée",
                    "exercice": exercice_note,
                    "montant": str(total_note),
                    "poste_code": note.budget_poste_code,
                }
            ]
        categorie_expert = categorie_membre(expert.type_ec, expert.statut_professionnel)

        # Imputation sur la dette la plus ancienne ; à exercice égal, l'ordre
        # de la note (tri stable).
        lignes_note = sorted(lignes_note, key=lambda a: int(a.get("exercice") or exercice_note))
        for article in lignes_note:
            montant_article = max(Decimal(str(article.get("montant") or 0)), zero)
            exercice_article = int(article.get("exercice") or exercice_note)
            paye_article = min(montant_article, a_imputer)
            a_imputer -= paye_article
            reste_article = montant_article - paye_article

            # Une cotisation N+1 déjà réglée est un paiement anticipatif du
            # point de vue de l'exercice N. Sa dette future n'alourdit pas le
            # reste exigible de N.
            if exercice_article > annee:
                groupe["avance_n_plus_1"] += paye_article
                continue

            categorie = article.get("categorie") or LEGACY
            libelle = str(article.get("libelle") or libelle_categorie(categorie))
            groupe["total_creances"] += montant_article
            groupe["reglements"] += paye_article
            groupe["reste_du"] += reste_article

            if categorie in categories_cotisation:
                cle = "cotisations_anterieures" if exercice_article < annee else "cotisation_n"
            elif categorie in categories_penalite:
                cle = "penalites_anterieures" if exercice_article < annee else "penalites_n"
            elif categorie == LEGACY:
                poste = article.get("poste_code") or note.budget_poste_code
                cle = colonne_situation(
                    rattachements.colonne(poste, categorie_expert, libelle),
                    libelle=libelle,
                    exercice=exercice_article,
                    annee=annee,
                )
            else:
                cle = "autres_creances"
            groupe["restes"][cle] += reste_article
            if cle != "autres_creances":
                groupe[cle] += montant_article
            else:
                groupe["autres_creances"] += montant_article
                groupe["autres_details"].append(
                    {
                        "libelle": libelle,
                        "exercice": exercice_article,
                        "montant": argent(montant_article),
                        "paye": argent(paye_article),
                        "reste": argent(reste_article),
                    }
                )
    return groupes


async def articles_par_note(db: AsyncSession, note_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not note_ids:
        return {}
    lignes = (
        await db.execute(
            select(EncaissementArticle, BudgetPoste.code)
            .outerjoin(BudgetPoste, BudgetPoste.id == EncaissementArticle.budget_poste_id)
            .where(EncaissementArticle.encaissement_id.in_(note_ids))
            .order_by(EncaissementArticle.encaissement_id, EncaissementArticle.sort_order)
        )
    ).all()
    resultat: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for article, code in lignes:
        resultat.setdefault(article.encaissement_id, []).append(
            {
                "libelle": article.libelle,
                "categorie": article.categorie or LEGACY,
                "categorie_libelle": libelle_categorie(article.categorie, article.libelle),
                "exercice": article.exercice,
                "reference_decision": article.reference_decision,
                "observation": article.description,
                "quantite": str(article.quantite),
                "prix_unitaire": str(article.prix_unitaire),
                "montant": str(article.montant),
                "poste_code": code,
            }
        )
    return resultat


async def cotisations_par_numero(db: AsyncSession, organisation_id: int, annee: int) -> dict[str, dict[str, Any]]:
    """Où en est la cotisation de chaque membre à la fin de `annee`, par n° d'ordre.

    Lecture seule, pour le Tableau : « la cotisation est réglée » se lit dans
    les notes de débit, avec le même calcul que la situation des membres. La
    clé est le n° d'ordre rapproché (`cle_numero_ordre`). Un membre sans aucune
    cotisation émise n'y figure pas : rien ne permet alors de trancher, et le
    Tableau garde ce que son import disait.

    Toutes les notes de l'organisation comptent, quel que soit le service : la
    cotisation d'un membre ne dépend pas de qui la consulte.
    """
    from datetime import datetime, timezone

    from app.services.notes_debit_import import cle_numero_ordre

    fin = datetime(annee + 1, 1, 1, tzinfo=timezone.utc)
    lignes = list(
        (
            await db.execute(
                select(Encaissement, ExpertComptable)
                .join(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
                .where(
                    Encaissement.organisation_id == organisation_id,
                    Encaissement.is_deleted.is_(False),
                    Encaissement.est_proforma.is_(False),
                    Encaissement.statut_operation != "ANNULEE",
                    Encaissement.type_client.in_(("expert_comptable", "sec")),
                    or_(Encaissement.date_encaissement < fin, Encaissement.exercice <= annee),
                )
                .order_by(Encaissement.date_encaissement, Encaissement.numero_recu)
            )
        ).all()
    )
    if not lignes:
        return {}
    articles = await articles_par_note(db, [note.id for note, _ in lignes])
    groupes = calculer_situation(lignes, articles, await classeur(db, organisation_id), annee)

    resultat: dict[str, dict[str, Any]] = {}
    for groupe in groupes.values():
        cle = cle_numero_ordre(groupe["expert"]["numero_ordre"])
        du_n = groupe["cotisation_n"]
        du_anterieur = groupe["cotisations_anterieures"]
        if not cle or (du_n + du_anterieur) <= 0:
            continue
        reste_n = groupe["restes"]["cotisation_n"]
        reste_anterieur = groupe["restes"]["cotisations_anterieures"]
        paye = (du_n - reste_n) + (du_anterieur - reste_anterieur)
        if reste_n <= 0 and reste_anterieur <= 0:
            etat = "payee"
        elif paye > 0:
            etat = "partielle"
        else:
            etat = "non_payee"
        resultat[cle] = {
            # La cotisation N n'est réglée que si les arriérés de cotisation le
            # sont aussi : un versement va d'abord à la dette la plus ancienne.
            "payee": etat == "payee",
            "etat": etat,
            "du_n": argent(du_n),
            "reste_n": argent(reste_n),
            "du_anterieur": argent(du_anterieur),
            "reste_anterieur": argent(reste_anterieur),
            "nb_notes": groupe["nb_notes"],
        }
    return resultat
