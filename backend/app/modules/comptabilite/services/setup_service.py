"""Provisioning explicite de la comptabilité pour une organisation.

Déclenché uniquement à la demande (bouton « Activer la comptabilité »),
jamais automatiquement — cf. contrainte C4 du dossier d'architecture (le
clonage inter-tenant ne doit jamais produire un plan comptable fantôme).

Idempotent : rejouable sans effet si la société par défaut existe déjà.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaExercice,
    ComptaJournal,
    ComptaSociete,
)
from app.modules.comptabilite.services.plans_comptables import seeder_referentiel
from app.modules.comptabilite.services.plans_etats import seeder_etats_financiers

# Journaux de démarrage couvrant les faits générateurs déjà présents dans
# l'application (encaissements, sorties de fonds, transferts internes, paie),
# plus la clôture d'exercice et le report des à-nouveaux (Lot 5).
JOURNAUX_PAR_DEFAUT: list[tuple[str, str, str]] = [
    ("CA", "Caisse", "CA"),
    ("BQ", "Banque", "BQ"),
    ("OD", "Opérations diverses", "OD"),
    ("SAL", "Salaires", "SAL"),
    ("CLO", "Clôture d'exercice", "CLO"),
    ("AN", "Report à nouveau", "AN"),
]


async def setup_comptabilite(
    db: AsyncSession,
    *,
    organisation_id: int,
    organisation_nom: str,
    type_referentiel: str,
    exercice_date_debut: date,
    exercice_date_fin: date,
) -> dict:
    """Provisionne société, référentiel+plan, journaux et exercice courant.

    Retourne un dict serialisable (pas les objets ORM) pour rester simple côté
    router ; `deja_existant=True` si la société par défaut existait déjà,
    auquel cas rien n'est recréé (idempotence).
    """
    existing = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == organisation_id,
            ComptaSociete.is_default.is_(True),
        )
    )
    societe = existing.scalar_one_or_none()
    deja_existant = societe is not None

    if societe is None:
        societe = ComptaSociete(
            organisation_id=organisation_id,
            code="PRINCIPALE",
            raison_sociale=organisation_nom,
            is_default=True,
        )
        db.add(societe)
        await db.flush()

    referentiel = await seeder_referentiel(
        db,
        organisation_id=organisation_id,
        type_referentiel=type_referentiel,
        code=type_referentiel,
        libelle=f"Plan {type_referentiel}",
        is_default=True,
    )

    journaux_ids: list[int] = []
    for code, libelle, type_journal in JOURNAUX_PAR_DEFAUT:
        res = await db.execute(
            select(ComptaJournal).where(
                ComptaJournal.organisation_id == organisation_id,
                ComptaJournal.societe_id == societe.id,
                ComptaJournal.code == code,
            )
        )
        journal = res.scalar_one_or_none()
        if journal is None:
            journal = ComptaJournal(
                organisation_id=organisation_id,
                societe_id=societe.id,
                code=code,
                libelle=libelle,
                type_journal=type_journal,
            )
            db.add(journal)
            await db.flush()
        journaux_ids.append(journal.id)

    if exercice_date_fin <= exercice_date_debut:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La date de fin d'exercice doit être postérieure à la date de début.",
        )
    exercice_code = str(exercice_date_debut.year)
    res = await db.execute(
        select(ComptaExercice).where(
            ComptaExercice.organisation_id == organisation_id,
            ComptaExercice.societe_id == societe.id,
            ComptaExercice.code == exercice_code,
        )
    )
    exercice = res.scalar_one_or_none()
    if exercice is None:
        exercice = ComptaExercice(
            organisation_id=organisation_id,
            societe_id=societe.id,
            code=exercice_code,
            libelle=f"Exercice {exercice_code}",
            date_debut=exercice_date_debut,
            date_fin=exercice_date_fin,
            referentiel_id=referentiel.id,
            statut="OUVERT",
        )
        db.add(exercice)
        await db.flush()

    # Structures des états financiers (Lot 5). Idempotent : ne réécrit jamais
    # un paramétrage déjà affiné par l'organisation.
    resume_etats = await seeder_etats_financiers(
        db, organisation_id=organisation_id, referentiel_id=referentiel.id
    )

    nb_comptes = (
        await db.execute(
            select(ComptaCompte).where(ComptaCompte.referentiel_id == referentiel.id)
        )
    ).scalars().all()

    return {
        "societe_id": societe.id,
        "referentiel_id": referentiel.id,
        "exercice_id": exercice.id,
        "journaux_ids": journaux_ids,
        "nb_comptes": len(nb_comptes),
        "nb_postes_etat": resume_etats["postes_crees"],
        "deja_existant": deja_existant,
    }
