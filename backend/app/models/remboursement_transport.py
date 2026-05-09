from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RemboursementTransport(Base):
    __tablename__ = "remboursements_transport"
    __table_args__ = (
        UniqueConstraint("organisation_id", "numero_remboursement", name="uq_remboursements_transport_org_numero"),
        UniqueConstraint("organisation_id", "reference_numero", name="uq_remboursements_transport_org_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    numero_remboursement: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True)
    instance: Mapped[str] = mapped_column(String(100), nullable=False)
    type_reunion: Mapped[str] = mapped_column(String(30), nullable=False)
    nature_reunion: Mapped[str] = mapped_column(String(200), nullable=False)
    nature_travail: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    lieu: Mapped[str] = mapped_column(String(200), nullable=False)
    date_reunion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heure_debut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    heure_fin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("requisitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trans_titre_officiel_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trans_label_gauche_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trans_nom_gauche_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trans_label_droite_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trans_nom_droite_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_g_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_g_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_d_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_d_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ParticipantTransport(Base):
    __tablename__ = "participants_transport"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    remboursement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("remboursements_transport.id", ondelete="CASCADE"),
        nullable=False,
    )
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    titre_fonction: Mapped[str] = mapped_column(String(200), nullable=False)
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    type_participant: Mapped[str] = mapped_column(String(20), nullable=False)
    expert_comptable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experts_comptables.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
