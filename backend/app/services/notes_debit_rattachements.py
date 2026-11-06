"""Paramètres des notes de débit : à quel poste de recette chaque colonne se rattache.

Voir `app.models.note_debit_rattachement`. Ce module lit et enregistre les
rattachements, et propose un premier jeu tiré des libellés du budget quand le
conseil n'a encore rien réglé : la proposition s'affiche comme telle, elle ne
s'enregistre que si quelqu'un la valide.
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.note_debit_rattachement import NoteDebitRattachement
from app.services.notes_debit_import import postes_disponibles

TOUTES = "*"

#: Les colonnes de la situation des membres, dans leur ordre d'affichage.
COLONNES: list[tuple[str, str]] = [
    ("cotisations_anterieures", "Cotisations ≤ N-1"),
    ("penalites_anterieures", "Pénalités ≤ N-1"),
    ("cotisation_n", "Cotisation N"),
    ("penalites_n", "Pénalités N"),
    ("autres_creances", "Autres créances"),
]
CLES_COLONNES = {cle for cle, _ in COLONNES}

#: Catégories de membre qui reçoivent des notes de débit.
CATEGORIES: list[str] = ["EC Cabinet", "EC Indépendant", "EC Salarié", "Société"]


def categorie_membre(type_ec: str | None, statut_professionnel: str | None) -> str | None:
    """La catégorie d'un expert telle que les rattachements la nomment."""
    if (type_ec or "").upper() == "SEC":
        return "Société"
    statut = _cle(statut_professionnel)
    if "cabinet" in statut:
        return "EC Cabinet"
    if "independ" in statut:
        return "EC Indépendant"
    if "salari" in statut:
        return "EC Salarié"
    return None


def _cle(valeur: str | None) -> str:
    texte = unicodedata.normalize("NFKD", valeur or "")
    return " ".join("".join(c for c in texte if not unicodedata.combining(c)).lower().split())


async def _postes(db: AsyncSession, tenant_id: int) -> list[BudgetPoste]:
    _exercice, postes = await postes_disponibles(db, tenant_id, None)
    return postes


def _suggestions(postes: list[BudgetPoste]) -> list[dict[str, str]]:
    """Un premier rattachement tiré des libellés du budget, à faire valider.

    Ne propose que ce qu'un libellé désigne sans ambiguïté : un seul poste
    candidat, sinon rien. Les pénalités n'ont souvent pas encore de poste : la
    case reste vide plutôt que de tomber sur un poste approchant.
    """
    def unique(*mots: str, sans: tuple[str, ...] = ()) -> str | None:
        trouves = [
            p.code for p in postes
            if all(m in _cle(p.libelle) for m in mots) and not any(s in _cle(p.libelle) for s in sans)
        ]
        trouves = list(dict.fromkeys(c for c in trouves if c))
        return trouves[0] if len(trouves) == 1 else None

    proposes: list[dict[str, str]] = []

    def ajouter(colonne: str, categorie: str, code: str | None) -> None:
        if code:
            proposes.append({"colonne": colonne, "categorie_membre": categorie, "budget_poste_code": code})

    ajouter("cotisations_anterieures", TOUTES, unique("arriere", "cotisation"))
    ajouter("penalites_anterieures", TOUTES, unique("arriere", "penalit"))
    ajouter("penalites_n", TOUTES, unique("penalit", sans=("arriere",)))
    ajouter("cotisation_n", "EC Cabinet", unique("cabinet", sans=("arriere", "societe", "nouvellement")))
    ajouter("cotisation_n", "EC Indépendant", unique("independ", sans=("arriere",)))
    ajouter("cotisation_n", "EC Salarié", unique("salari", sans=("arriere",)))
    ajouter("cotisation_n", "Société", unique("societe", sans=("arriere", "nouvellement", "inscription")))
    return proposes


async def lire_rattachements(db: AsyncSession, tenant_id: int) -> list[NoteDebitRattachement]:
    return list(
        (
            await db.execute(
                select(NoteDebitRattachement)
                .where(NoteDebitRattachement.organisation_id == tenant_id)
                .order_by(NoteDebitRattachement.colonne, NoteDebitRattachement.categorie_membre)
            )
        ).scalars().all()
    )


async def parametres(db: AsyncSession, tenant_id: int) -> dict[str, Any]:
    postes = await _postes(db, tenant_id)
    lignes = await lire_rattachements(db, tenant_id)
    codes = {p.code for p in postes}
    return {
        "colonnes": [{"cle": cle, "libelle": libelle} for cle, libelle in COLONNES],
        "categories": CATEGORIES,
        "postes": [
            {"code": p.code, "libelle": p.libelle}
            for p in sorted({p.code: p for p in postes if p.code}.values(), key=lambda p: p.code)
        ],
        "rattachements": [
            {
                "colonne": ligne.colonne,
                "categorie_membre": ligne.categorie_membre,
                "budget_poste_code": ligne.budget_poste_code,
                # Le code ne désigne plus aucun poste de recette de l'exercice
                # en cours : il a été renuméroté ou supprimé.
                "introuvable": ligne.budget_poste_code not in codes,
            }
            for ligne in lignes
        ],
        "suggestions": _suggestions(postes) if not lignes else [],
    }


async def enregistrer(
    db: AsyncSession, tenant_id: int, user_id: uuid.UUID | None, rattachements: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Remplace les rattachements du conseil. Un code inconnu du budget est refusé."""
    codes = {p.code for p in await _postes(db, tenant_id)}
    retenus: dict[tuple[str, str], str] = {}
    for item in rattachements:
        colonne = (item.get("colonne") or "").strip()
        categorie = (item.get("categorie_membre") or TOUTES).strip() or TOUTES
        code = (item.get("budget_poste_code") or "").strip()
        if not code:
            continue
        if colonne not in CLES_COLONNES:
            raise HTTPException(status_code=422, detail=f"Colonne inconnue : « {colonne} ».")
        if categorie != TOUTES and categorie not in CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Catégorie inconnue : « {categorie} ».")
        if code not in codes:
            raise HTTPException(
                status_code=422,
                detail=f"Le poste « {code} » n'est pas un poste de recette actif de l'exercice en cours.",
            )
        retenus[(colonne, categorie)] = code

    await db.execute(delete(NoteDebitRattachement).where(NoteDebitRattachement.organisation_id == tenant_id))
    for (colonne, categorie), code in retenus.items():
        db.add(
            NoteDebitRattachement(
                organisation_id=tenant_id,
                colonne=colonne,
                categorie_membre=categorie,
                budget_poste_code=code,
                updated_by=user_id,
            )
        )
    await db.flush()
    return [
        {"colonne": colonne, "categorie_membre": categorie, "budget_poste_code": code}
        for (colonne, categorie), code in sorted(retenus.items())
    ]


async def poste_par_colonne(db: AsyncSession, tenant_id: int) -> dict[str, list[dict[str, Any]]]:
    """Pour l'en-tête de la situation : colonne → [{catégorie, code, libellé}]."""
    libelles = {p.code: p.libelle for p in await _postes(db, tenant_id)}
    resultat: dict[str, list[dict[str, Any]]] = {cle: [] for cle, _ in COLONNES}
    for ligne in await lire_rattachements(db, tenant_id):
        resultat.setdefault(ligne.colonne, []).append(
            {
                "categorie_membre": ligne.categorie_membre,
                "code": ligne.budget_poste_code,
                "libelle": libelles.get(ligne.budget_poste_code),
            }
        )
    return resultat


def _sans_accents(valeur: str | None) -> str:
    return _cle(valeur)


class Classeur:
    """Range une créance dans une colonne de la situation d'après son poste.

    Une note ancienne n'a souvent qu'un poste et un libellé, sans nature de
    créance. Les rattachements disent quelle colonne alimente chaque poste ; on
    lit le chemin à l'envers : ce poste-ci appartient à telle colonne.

    Quand un même poste sert deux colonnes (par exemple un seul poste
    d'arriérés pour les cotisations et les pénalités antérieures), le libellé
    départage ; à défaut, la première colonne dans l'ordre de la situation.
    """

    def __init__(self, lignes: list[NoteDebitRattachement]):
        generaux: dict[str, str] = {}
        propres: dict[str, dict[str, str]] = {}
        for ligne in lignes:
            if ligne.categorie_membre == TOUTES:
                generaux[ligne.colonne] = ligne.budget_poste_code
            else:
                propres.setdefault(ligne.categorie_membre, {})[ligne.colonne] = ligne.budget_poste_code
        self._inverse: dict[str | None, dict[str, list[str]]] = {}
        for categorie in [None, *CATEGORIES]:
            effectif = {**generaux, **(propres.get(categorie, {}) if categorie else {})}
            inverse: dict[str, list[str]] = {}
            for colonne, _libelle in COLONNES:
                code = effectif.get(colonne)
                if code:
                    inverse.setdefault(code.strip().upper(), []).append(colonne)
            self._inverse[categorie] = inverse
        # Un poste rattaché pour une catégorie vaut aussi, à défaut de mieux,
        # pour un membre dont la catégorie est inconnue.
        tous: dict[str, list[str]] = {}
        for inverse in self._inverse.values():
            for code, colonnes in inverse.items():
                for colonne in colonnes:
                    if colonne not in tous.setdefault(code, []):
                        tous[code].append(colonne)
        self._tous = {code: sorted(cols, key=[c for c, _ in COLONNES].index) for code, cols in tous.items()}

    def colonne(self, code: str | None, categorie: str | None, libelle: str | None) -> str | None:
        """La colonne de ce poste, ou None s'il n'est rattaché à aucune."""
        if not code:
            return None
        cle_code = code.strip().upper()
        candidates = self._inverse.get(categorie, {}).get(cle_code) or self._tous.get(cle_code) or []
        if len(candidates) <= 1:
            return candidates[0] if candidates else None
        texte = _sans_accents(libelle)
        if "penalit" in texte:
            choix = [c for c in candidates if c.startswith("penalites")]
        elif "cotis" in texte or "arriere" in texte:
            choix = [c for c in candidates if c.startswith("cotisation")]
        else:
            choix = []
        return (choix or candidates)[0]


async def classeur(db: AsyncSession, tenant_id: int) -> Classeur:
    return Classeur(await lire_rattachements(db, tenant_id))


def colonne_situation(
    colonne: str | None, *, libelle: str | None, exercice: int, annee: int
) -> str:
    """La colonne finale, en tenant compte de l'exercice de la créance.

    Le poste dit la nature (cotisation, pénalité, autre) ; l'exercice dit si
    elle est de N ou antérieure. Une créance d'un poste non rattaché se range
    d'après son libellé, puis dans « Autres créances ».
    """
    if colonne is None:
        texte = _sans_accents(libelle)
        if "penalit" in texte:
            colonne = "penalites_n"
        elif "arriere" in texte and "cotis" in texte:
            colonne = "cotisations_anterieures"
        elif "cotis" in texte:
            colonne = "cotisation_n"
        else:
            return "autres_creances"
    anterieure = exercice < annee
    if colonne == "cotisation_n" and anterieure:
        return "cotisations_anterieures"
    if colonne == "penalites_n" and anterieure:
        return "penalites_anterieures"
    return colonne
