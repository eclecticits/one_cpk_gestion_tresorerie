from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClotureCaisse(Base):
    __tablename__ = "clotures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference_numero: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    date_cloture: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    date_debut: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caissier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    solde_initial_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_initial_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    total_entrees_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_entrees_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_sorties_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_sorties_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    solde_theorique_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_theorique_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_physique_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_physique_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ecart_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ecart_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    taux_change_applique: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=1)

    billetage_usd: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    billetage_cdf: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    observation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="VALIDEE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
