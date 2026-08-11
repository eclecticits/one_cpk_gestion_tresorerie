from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RegularisationCaisse(Base):
    """Trace d'un écart de caisse résorbé par une opération financière.

    Règle métier : un comptage physique ne remplace JAMAIS le solde théorique.
    L'écart constaté donne lieu à une opération identifiable — un encaissement
    si le physique excède le théorique, une sortie dans le cas inverse — et
    c'est cette opération qui déplace le solde. Cette table relie l'écart
    (constaté à une ouverture ou à une clôture) à l'opération qui l'a résorbé.

    Un écart laissé sans régularisation n'a simplement aucune ligne ici : les
    ouvertures et clôtures dont l'écart est non nul et sans ligne associée sont
    les « écarts non régularisés ».
    """

    __tablename__ = "regularisations_caisse"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('OUVERTURE','CLOTURE')",
            name="ck_regularisations_caisse_source_type",
        ),
        CheckConstraint(
            "sens IN ('EXCEDENT','DEFICIT')",
            name="ck_regularisations_caisse_sens",
        ),
        CheckConstraint(
            "devise IN ('USD','CDF')",
            name="ck_regularisations_caisse_devise",
        ),
        CheckConstraint("montant > 0", name="ck_regularisations_caisse_montant_positif"),
        # Un excédent est porté par un encaissement, un déficit par une sortie :
        # exactement une des deux références est renseignée.
        CheckConstraint(
            "(encaissement_id IS NOT NULL AND sortie_fonds_id IS NULL) OR "
            "(encaissement_id IS NULL AND sortie_fonds_id IS NOT NULL)",
            name="ck_regularisations_caisse_operation_unique",
        ),
        Index(
            "ix_regularisations_caisse_source",
            "organisation_id",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Origine de l'écart : la ligne d'ouvertures_caisse ou de clotures.
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)

    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    sens: Mapped[str] = mapped_column(String(20), nullable=False)
    # Toujours positif : le sens porte la direction.
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    solde_theorique: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    solde_physique: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)

    encaissement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encaissements.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    sortie_fonds_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sorties_fonds.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    motif: Mapped[str] = mapped_column(Text, nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
