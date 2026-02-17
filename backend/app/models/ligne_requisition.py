from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LigneRequisition(Base):
    __tablename__ = "lignes_requisition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requisition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id"),
        nullable=True,
        index=True,
    )
    rubrique: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    montant_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
