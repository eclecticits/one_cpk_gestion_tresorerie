"""Numérotation des pièces comptables.

Distinct de `app/services/document_sequences.py` :
- les codes OD / CLO / OUV y sont déjà utilisés par d'autres modules ;
- la numérotation comptable est calée sur l'EXERCICE et le JOURNAL,
  pas sur l'année civile.

Format produit : ``{JOURNAL}-{EXERCICE}-{00001}``  (ex. ``BQ-2026-00042``).

Concurrence : le compteur est verrouillé (``SELECT ... FOR UPDATE``) le temps de
la transaction, sur le modèle de `document_sequences`. Deux saisies simultanées
sur le même journal ne peuvent donc pas obtenir le même numéro.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaExercice,
    ComptaJournal,
    ComptaSequence,
)

# Au-delà, le format à 5 chiffres déborde : on préfère échouer explicitement
# plutôt que produire des numéros incohérents.
COMPTEUR_MAX = 99_999


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def generer_numero_ecriture(
    db: AsyncSession,
    *,
    organisation_id: int,
    societe_id: int,
    exercice_id: int,
    journal_id: int,
) -> str:
    """Réserve et retourne le prochain numéro de pièce pour un journal donné.

    À appeler UNIQUEMENT au moment de la validation d'une écriture : un
    brouillon ne consomme pas de numéro (sinon la séquence présenterait des
    trous, ce qu'un auditeur relève systématiquement).
    """
    journal = await db.get(ComptaJournal, journal_id)
    if journal is None or journal.organisation_id != organisation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal introuvable")
    if journal.societe_id != societe_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le journal n'appartient pas à cette société",
        )

    exercice = await db.get(ComptaExercice, exercice_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if exercice.societe_id != societe_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'exercice n'appartient pas à cette société",
        )

    # Verrou sur le compteur pour la durée de la transaction.
    res = await db.execute(
        select(ComptaSequence)
        .where(
            ComptaSequence.organisation_id == organisation_id,
            ComptaSequence.societe_id == societe_id,
            ComptaSequence.exercice_id == exercice_id,
            ComptaSequence.journal_id == journal_id,
        )
        .with_for_update()
    )
    sequence = res.scalar_one_or_none()

    if sequence is None:
        sequence = ComptaSequence(
            organisation_id=organisation_id,
            societe_id=societe_id,
            exercice_id=exercice_id,
            journal_id=journal_id,
            compteur=1,
            updated_at=_utcnow(),
        )
        db.add(sequence)
        # flush() matérialise l'INSERT : en cas de création concurrente, la
        # contrainte d'unicité tranche immédiatement plutôt qu'au commit.
        await db.flush()
    else:
        if sequence.compteur >= COMPTEUR_MAX:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Capacité de numérotation atteinte pour le journal {journal.code} "
                    f"sur l'exercice {exercice.code}."
                ),
            )
        sequence.compteur += 1
        sequence.updated_at = _utcnow()
        await db.flush()

    return f"{journal.code}-{exercice.code}-{sequence.compteur:05d}"
