from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_requisition: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    objet: Mapped[str] = mapped_column(Text, nullable=False)
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False)
    type_requisition: Mapped[str] = mapped_column(String(50), nullable=False, default="classique")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="EN_ATTENTE", index=True)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    validee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    validee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approuvee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approuvee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)
    a_valoir: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instance_beneficiaire: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes_a_valoir: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    import_source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    req_titre_officiel_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    req_label_gauche_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    req_nom_gauche_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    req_label_droite_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    req_nom_droite_hist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_g_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_g_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_d_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signataire_d_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
