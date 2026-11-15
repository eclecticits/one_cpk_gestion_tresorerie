"""Attestations comptables de cotisation : lecture et écriture.

Voir `app.models.cotisation_attestation`. Une attestation vaut pour un membre
et un exercice ; elle ne porte aucun montant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cotisation_attestation import CotisationAttestation
from app.services.audit_service import log_action


async def attestations_de(
    db: AsyncSession, organisation_id: int, exercice: int, expert_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, CotisationAttestation]:
    """Les attestations de l'exercice, par membre."""
    requete = select(CotisationAttestation).where(
        CotisationAttestation.organisation_id == organisation_id,
        CotisationAttestation.exercice == exercice,
    )
    if expert_ids is not None:
        if not expert_ids:
            return {}
        requete = requete.where(CotisationAttestation.expert_comptable_id.in_(expert_ids))
    return {a.expert_comptable_id: a for a in (await db.execute(requete)).scalars().all()}


async def attester(
    db: AsyncSession, organisation_id: int, exercice: int, expert_ids: list[uuid.UUID], user_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Atteste les membres qui ne le sont pas encore ; rend ceux qui viennent de l'être."""
    deja = await attestations_de(db, organisation_id, exercice, expert_ids)
    nouveaux = [i for i in dict.fromkeys(expert_ids) if i not in deja]
    for expert_id in nouveaux:
        db.add(
            CotisationAttestation(
                organisation_id=organisation_id,
                expert_comptable_id=expert_id,
                exercice=exercice,
                created_by=user_id,
            )
        )
    await db.flush()
    return nouveaux


async def retirer(
    db: AsyncSession, organisation_id: int, exercice: int, expert_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Retire les attestations ; rend les membres qui en avaient une."""
    concernes = list(await attestations_de(db, organisation_id, exercice, expert_ids))
    if concernes:
        await db.execute(
            delete(CotisationAttestation).where(
                CotisationAttestation.organisation_id == organisation_id,
                CotisationAttestation.exercice == exercice,
                CotisationAttestation.expert_comptable_id.in_(concernes),
            )
        )
        await db.flush()
    return concernes


async def retirer_au_paiement(
    db: AsyncSession, *, organisation_id: int, note: Any, annee_paiement: int, user_id: uuid.UUID | None
) -> list[int]:
    """Un versement sur une note du membre fait disparaître son attestation.

    L'attestation est un raccourci en attendant l'encaissement : dès que la
    caisse ou la banque encaisse, la situation des notes fait de nouveau foi.
    Sont retirées les attestations de l'exercice de la note et des suivants ;
    rend les exercices concernés.
    """
    if note.expert_comptable_id is None or note.type_client not in ("expert_comptable", "sec"):
        return []
    exercice_note = note.exercice or annee_paiement
    exercices = list(
        (
            await db.execute(
                delete(CotisationAttestation)
                .where(
                    CotisationAttestation.organisation_id == organisation_id,
                    CotisationAttestation.expert_comptable_id == note.expert_comptable_id,
                    CotisationAttestation.exercice >= exercice_note,
                )
                .returning(CotisationAttestation.exercice)
            )
        ).scalars().all()
    )
    for exercice in exercices:
        await log_action(
            db,
            user_id=user_id,
            action="COTISATION_ATTESTATION_RETIREE",
            target_table="experts_comptables",
            target_id=str(note.expert_comptable_id),
            new_value={"exercice": exercice, "en_ordre": False, "motif": "paiement", "note_id": str(note.id)},
        )
    return exercices
