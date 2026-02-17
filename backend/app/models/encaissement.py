from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Encaissement(Base):
    __tablename__ = "encaissements"
    __table_args__ = (
        CheckConstraint("montant >= 0", name="ck_encaissements_montant_nonneg"),
        CheckConstraint("montant_total >= 0", name="ck_encaissements_montant_total_nonneg"),
        CheckConstraint("montant_paye >= 0", name="ck_encaissements_montant_paye_nonneg"),
        CheckConstraint(
            "type_client IN ('expert_comptable','client_externe','banque_institution','partenaire','organisation','autre')",
            name="ck_encaissements_type_client",
        ),
        CheckConstraint(
            "statut_paiement IN ('non_paye','partiel','complet','avance')",
            name="ck_encaissements_statut_paiement",
        ),
        CheckConstraint(
            "mode_paiement IN ('cash','mobile_money','virement')",
            name="ck_encaissements_mode_paiement",
        ),
        CheckConstraint(
            "devise_perception IN ('USD','CDF')",
            name="ck_encaissements_devise_perception",
        ),
        CheckConstraint(
            "(type_client = 'expert_comptable' AND expert_comptable_id IS NOT NULL) OR "
            "(type_client <> 'expert_comptable' AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)",
            name="ck_encaissements_client_ref",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_recu: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    
    # Type de client: expert_comptable, client_externe, banque_institution, partenaire, organisation, autre
    type_client: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Si type_client == expert_comptable
    expert_comptable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experts_comptables.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Si autre type de client
    client_nom: Mapped[str | None] = mapped_column(String(300), nullable=True)
    
    # Type d'opération (cotisation_annuelle, inscription_tableau, etc.)
    type_operation: Mapped[str] = mapped_column(String(100), nullable=False)
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Montants
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_paye: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_percu: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    devise_perception: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    taux_change_applique: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=1)

    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id"),
        nullable=True,
        index=True,
    )
    budget_poste_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_poste_libelle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # non_paye, partiel, complet, avance
    statut_paiement: Mapped[str] = mapped_column(String(20), nullable=False, default="non_paye")
    
    # cash, mobile_money, virement
    mode_paiement: Mapped[str] = mapped_column(String(30), nullable=False, default="cash")
    
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    date_encaissement: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    # Relation avec PaymentHistory (sera définie après)
    # payment_history = relationship("PaymentHistory", back_populates="encaissement")
