from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequisitionFondsTiers(Base):
    """Fonds de tiers qu'une réquisition autorise à reverser, et pour combien.

    Un seul versement peut solder plusieurs encaissements reçus pour compte
    d'autrui : la réquisition les nomme un à un. Le destinataire, lui, reste
    porté par la réquisition (`tiers_organisation_id` / `tiers_nom_libre`) et
    peut différer du tiers enregistré à l'encaissement — c'est ce lien explicite,
    et non l'égalité des noms, qui autorise alors le paiement.
    """

    __tablename__ = "requisition_fonds_tiers"
    __table_args__ = (
        CheckConstraint("montant > 0", name="ck_requisition_fonds_tiers_montant"),
        UniqueConstraint("requisition_id", "fonds_tiers_operation_id", name="uq_requisition_fonds_tiers"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requisitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fonds_tiers_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fonds_tiers_operations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class SortieFondsTiers(Base):
    """Part d'une sortie de fonds imputée sur chaque fonds de tiers reversé.

    Source unique du « déjà reversé » d'un fonds : une sortie qui en solde
    plusieurs y écrit une ligne par fonds. `sorties_fonds.fonds_tiers_operation_id`
    n'est renseigné que lorsque la sortie ne vise qu'un seul fonds.
    """

    __tablename__ = "sortie_fonds_tiers"
    __table_args__ = (
        CheckConstraint("montant > 0", name="ck_sortie_fonds_tiers_montant"),
        UniqueConstraint("sortie_fonds_id", "fonds_tiers_operation_id", name="uq_sortie_fonds_tiers"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sortie_fonds_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sorties_fonds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fonds_tiers_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fonds_tiers_operations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
