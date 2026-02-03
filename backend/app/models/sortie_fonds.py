from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Numeric, String, Text
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

    montant_paye: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    date_paiement: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    motif: Mapped[str] = mapped_column(Text, nullable=False)
    beneficiaire: Mapped[str] = mapped_column(String(200), nullable=False)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
