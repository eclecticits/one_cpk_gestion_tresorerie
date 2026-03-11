from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SortieFonds(Base):
    __tablename__ = "sorties_fonds"
    __table_args__ = (
        CheckConstraint(
            "canal IN ('CAISSE','BANQUE')",
            name="ck_sorties_fonds_canal",
        ),
        CheckConstraint(
            "devise IN ('USD','CDF')",
            name="ck_sorties_fonds_devise",
        ),
        CheckConstraint(
            "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR (canal = 'CAISSE')",
            name="ck_sorties_fonds_compte_bancaire",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_sortie: Mapped[str] = mapped_column(String(50), nullable=False)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id"),
        nullable=True,
        index=True,
    )

    montant_paye: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    date_paiement: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    canal: Mapped[str] = mapped_column(String(10), nullable=False, default="CAISSE")
    compte_bancaire_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("comptes_bancaires.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="VALIDE")
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    motif: Mapped[str] = mapped_column(Text, nullable=False)
    beneficiaire: Mapped[str] = mapped_column(String(200), nullable=False)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    annexes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    bank_statement_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    service: Mapped["Service | None"] = relationship("Service", back_populates="sorties_fonds")
    compte_bancaire = relationship("CompteBancaire", back_populates="sorties_fonds")
    organisation: Mapped["Organisation"] = relationship("Organisation")
