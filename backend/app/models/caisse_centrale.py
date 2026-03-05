from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaisseCentrale(Base):
    __tablename__ = "caisse_centrale"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    solde_usd: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    solde_cdf: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    derniere_maj: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
