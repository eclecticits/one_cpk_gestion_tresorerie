from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RegularisationBudgetaire(Base):
    """Décision auditée d'affectation d'un mouvement hors budget au budget."""

    __tablename__ = "regularisations_budgetaires"
    __table_args__ = (
        CheckConstraint(
            "(encaissement_id IS NOT NULL)::int + (sortie_fonds_id IS NOT NULL)::int = 1",
            name="ck_reg_budget_exactly_one_source",
        ),
        CheckConstraint("devise_mouvement IN ('USD','CDF')", name="ck_reg_budget_devise"),
        CheckConstraint("montant_mouvement > 0", name="ck_reg_budget_montant_mouvement_positif"),
        CheckConstraint("montant_budget >= 0", name="ck_reg_budget_montant_budget_nonneg"),
        UniqueConstraint("organisation_id", "idempotency_key", name="uq_reg_budget_org_idempotency"),
        Index("ix_reg_budget_encaissement", "encaissement_id"),
        Index("ix_reg_budget_sortie", "sortie_fonds_id"),
        Index("ix_reg_budget_org_created", "organisation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    encaissement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=True)
    sortie_fonds_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sorties_fonds.id", ondelete="RESTRICT"), nullable=True)
    ancien_nature_mouvement: Mapped[str] = mapped_column(String(40), nullable=False)
    nouveau_nature_mouvement: Mapped[str] = mapped_column(String(40), nullable=False, default="BUDGETAIRE")
    montant_mouvement: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    devise_mouvement: Mapped[str] = mapped_column(String(3), nullable=False)
    montant_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    encaissement = relationship("Encaissement")
    sortie_fonds = relationship("SortieFonds")
