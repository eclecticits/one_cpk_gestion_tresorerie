from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Requisition(Base):
    __tablename__ = "requisitions"
    __table_args__ = (
        UniqueConstraint("organisation_id", "numero_requisition", name="uq_requisitions_org_numero"),
        UniqueConstraint("organisation_id", "reference_numero", name="uq_requisitions_org_reference_numero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_requisition: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    objet: Mapped[str] = mapped_column(Text, nullable=False)
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False)
    type_requisition: Mapped[str] = mapped_column(String(50), nullable=False, default="classique")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="EN_ATTENTE", index=True)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    # Devise dans laquelle montant_total est exprimé (explicite plutôt qu'USD
    # implicite). Sert de base fiable pour la conversion vers la devise pivot.
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id"),
        nullable=True,
        index=True,
    )
    compte_bancaire_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("comptes_bancaires.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dossiers_requisition.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    validee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    validee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approuvee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approuvee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payee_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Photo du circuit de validation en vigueur à la CRÉATION de la réquisition.
    # Null pour les anciennes réquisitions => circuit complet par défaut.
    workflow_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    print_settings_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    organisation_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bank_account_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    signatories_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    historical_snapshot_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="not_finalized",
    )
    snapshot_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exchange_rate_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    base_amount_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    converted_amount_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    examen_status: Mapped[str] = mapped_column(String(30), nullable=False, default="NON_EXAMINE", index=True)
    examen_commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    examen_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    examen_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)
    a_valoir: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decaissement_progressif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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

    service: Mapped["Service | None"] = relationship("Service", back_populates="requisitions")
    dossier: Mapped["DossierRequisition | None"] = relationship("DossierRequisition", back_populates="requisitions")
    organisation: Mapped["Organisation"] = relationship("Organisation")
