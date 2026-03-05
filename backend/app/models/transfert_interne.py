from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransfertInterne(Base):
    __tablename__ = "transferts_internes"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('CAISSE','BANQUE')",
            name="ck_transferts_internes_source_type",
        ),
        CheckConstraint(
            "destination_type IN ('CAISSE','BANQUE')",
            name="ck_transferts_internes_destination_type",
        ),
        CheckConstraint(
            "devise IN ('USD','CDF')",
            name="ck_transferts_internes_devise",
        ),
        CheckConstraint(
            "(source_type = 'CAISSE' AND source_id IS NULL) OR "
            "(source_type = 'BANQUE' AND source_id IS NOT NULL)",
            name="ck_transferts_internes_source_ref",
        ),
        CheckConstraint(
            "(destination_type = 'CAISSE' AND destination_id IS NULL) OR "
            "(destination_type = 'BANQUE' AND destination_id IS NOT NULL)",
            name="ck_transferts_internes_destination_ref",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_type: Mapped[str] = mapped_column(String(10), nullable=False)
    destination_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_transfert: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    execute_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
