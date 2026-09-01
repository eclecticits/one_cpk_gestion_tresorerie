from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FondsTiersOperation(Base):
    """Suivi métier d'un fonds reçu pour compte de tiers.

    Le flux financier reste porté par encaissements/sorties_fonds. Cette table
    ne duplique pas la trésorerie ; elle relie l'entrée d'origine à ses
    remboursements et porte les informations propres au tiers.
    """

    __tablename__ = "fonds_tiers_operations"
    __table_args__ = (
        CheckConstraint(
            "statut IN ('OUVERT','PARTIELLEMENT_REMBOURSE','REGULARISE','ANNULE')",
            name="ck_fonds_tiers_statut",
        ),
        UniqueConstraint("organisation_id", "encaissement_id", name="uq_fonds_tiers_org_encaissement"),
        Index("ix_fonds_tiers_org_statut", "organisation_id", "statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    encaissement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=False, index=True)
    statut: Mapped[str] = mapped_column(String(40), nullable=False, default="OUVERT", index=True)
    tiers_concerne: Mapped[str] = mapped_column(String(255), nullable=False)
    payeur_origine: Mapped[str | None] = mapped_column(String(255), nullable=True)
    beneficiaire_reel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annulee_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)

    encaissement = relationship("Encaissement")
    organisation = relationship("Organisation")

