from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import uuid

from sqlalchemy import Boolean, DateTime, Integer, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaisseCentrale(Base):
    __tablename__ = "caisse_centrale"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    solde_usd: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    solde_cdf: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    derniere_maj: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # État de session de caisse (Modèle B). Une caisse fermée bloque toute
    # opération jusqu'à sa réouverture.
    est_ouverte: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ouverte_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ouverte_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
