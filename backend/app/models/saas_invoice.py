from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SaaSInvoice(Base):
    __tablename__ = "saas_invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    # DRAFT (brouillon) -> ISSUED (emise, en attente) -> PAID | CANCELLED.
    # Les factures nees d'un paiement en ligne naissent directement PAID.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PAID")
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Detail facture : [{designation, quantite, prix_unitaire}]. Absent sur les
    # factures historiques, generees automatiquement apres un paiement en ligne.
    line_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Identite de l'emetteur figee a l'emission : une piece comptable ne change
    # pas d'en-tete parce que l'adresse de la societe a bouge depuis.
    issuer_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    paid_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
