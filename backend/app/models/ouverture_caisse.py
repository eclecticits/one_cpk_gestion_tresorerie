from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OuvertureCaisse(Base):
    """Ouverture de caisse (début de session, Modèle B).

    Enregistre le fond de caisse compté au démarrage : montant + billetage,
    caissier, date. Miroir de ClotureCaisse pour la fin de session.
    """

    __tablename__ = "ouvertures_caisse"
    __table_args__ = (
        UniqueConstraint("organisation_id", "reference_numero", name="uq_ouvertures_org_reference_numero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reference_numero: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date_ouverture: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    caissier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    solde_ouverture_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_ouverture_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Solde attendu (report de la dernière clôture) et écart avec le fond compté.
    solde_attendu_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    solde_attendu_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ecart_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ecart_cdf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    billetage_usd: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    billetage_cdf: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    observation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="OUVERTE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
