from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MouvementBudgetImputation(Base):
    """Impact budgétaire figé produit par un mouvement financier réel."""

    __tablename__ = "mouvement_budget_imputations"
    __table_args__ = (
        CheckConstraint(
            "(encaissement_id IS NOT NULL)::int + "
            "(payment_history_id IS NOT NULL)::int + "
            "(sortie_fonds_id IS NOT NULL)::int + "
            "(retour_caisse_id IS NOT NULL)::int = 1",
            name="ck_mbi_exactly_one_source",
        ),
        CheckConstraint(
            "sens IN ('RECETTE_REALISEE','DEPENSE_PAYEE','RETOUR_DEPENSE')",
            name="ck_mbi_sens",
        ),
        CheckConstraint("statut IN ('ACTIVE','ANNULEE')", name="ck_mbi_statut"),
        CheckConstraint("devise_mouvement IN ('USD','CDF')", name="ck_mbi_devise"),
        CheckConstraint("montant_mouvement > 0", name="ck_mbi_montant_mouvement_positif"),
        CheckConstraint("montant_budget >= 0", name="ck_mbi_montant_budget_nonneg"),
        Index("ix_mbi_org_poste_statut", "organisation_id", "budget_poste_id", "statut"),
        Index("ix_mbi_encaissement", "encaissement_id"),
        Index("ix_mbi_payment_history", "payment_history_id"),
        Index("ix_mbi_sortie", "sortie_fonds_id"),
        Index("ix_mbi_retour", "retour_caisse_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    encaissement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=True)
    payment_history_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payment_history.id", ondelete="RESTRICT"), nullable=True)
    sortie_fonds_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sorties_fonds.id", ondelete="RESTRICT"), nullable=True)
    retour_caisse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("retours_caisse.id", ondelete="RESTRICT"), nullable=True)
    regularisation_budgetaire_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("regularisations_budgetaires.id", ondelete="RESTRICT"), nullable=True, index=True)
    budget_poste_id: Mapped[int] = mapped_column(Integer, ForeignKey("budget_postes.id", ondelete="RESTRICT"), nullable=False, index=True)
    sens: Mapped[str] = mapped_column(String(30), nullable=False)
    montant_mouvement: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    devise_mouvement: Mapped[str] = mapped_column(String(3), nullable=False)
    montant_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annulee_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    budget_poste = relationship("BudgetPoste")
    encaissement = relationship("Encaissement")
    payment_history = relationship("PaymentHistory")
    sortie_fonds = relationship("SortieFonds")
    retour_caisse = relationship("RetourCaisse")
    regularisation_budgetaire = relationship("RegularisationBudgetaire")
