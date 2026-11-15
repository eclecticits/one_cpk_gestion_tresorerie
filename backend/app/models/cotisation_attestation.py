"""Attestation comptable : « ce membre est en ordre de cotisation pour l'exercice ».

La comptabilité sait qu'un membre a payé avant que la caisse ne l'ait saisi :
paiement antérieur à la mise en service (régularisé en masse par poste
budgétaire, sans détail par membre) ou versement en banque pas encore
encaissé dans l'application. L'attestation le dit, et rien d'autre : elle ne
porte aucun montant, ne crée aucun encaissement et ne touche à aucun solde.
Le Tableau lit la cotisation comme réglée. C'est un raccourci en attendant
l'encaissement : au premier versement du membre, caisse ou banque,
l'attestation disparaît et la situation des notes fait de nouveau foi.

Retirer l'attestation supprime la ligne : le journal d'audit garde la trace.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CotisationAttestation(Base):
    __tablename__ = "cotisations_attestations"
    __table_args__ = (
        UniqueConstraint("organisation_id", "expert_comptable_id", "exercice", name="uq_cotisation_attestation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expert_comptable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experts_comptables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: L'exercice N de la situation des membres (celui du Tableau traité).
    exercice: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
