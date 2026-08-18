from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaymentHistory(Base):
    __tablename__ = "payment_history"
    __table_args__ = (
        # encaissement_id (FK non nulle) n'etait pas indexee alors que c'est
        # la seule cle de lookup de l'historique de paiement d'un recu, trie
        # sur created_at : chaque lecture forcait un scan complet de la table.
        Index(
            "ix_payment_history_encaissement_created",
            "encaissement_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    encaissement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encaissements.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="CAISSE")
    compte_bancaire_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_poste_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taux_change_applique: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"))
    date_paiement: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIF")
    statut_comptabilisation: Mapped[str] = mapped_column(String(40), nullable=False, default="NON_APPLICABLE")
    message_comptabilisation: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # cash, mobile_money, virement
    mode_paiement: Mapped[str] = mapped_column(String(30), nullable=False, default="cash")
    
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annule_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)
    annulation_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
