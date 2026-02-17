from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SortieFonds(Base):
    __tablename__ = "sorties_fonds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_sortie: Mapped[str] = mapped_column(String(50), nullable=False)
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    rubrique_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id"),
        nullable=True,
        index=True,
    )
    budget_poste_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_poste_libelle: Mapped[str | None] = mapped_column(String(255), nullable=True)

    montant_paye: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    date_paiement: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="VALIDE")
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)

    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    motif: Mapped[str] = mapped_column(Text, nullable=False)
    beneficiaire: Mapped[str] = mapped_column(String(200), nullable=False)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    annexes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
