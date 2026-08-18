from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LigneRequisition(Base):
    __tablename__ = "lignes_requisition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("requisitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id"),
        nullable=True,
        index=True,
    )
    # Intention de règlement de la ligne, saisie par le demandeur. Deux lignes
    # d'une même réquisition peuvent viser des modes — et des comptes bancaires —
    # différents ; c'est alors un règlement mixte, qui impose le décaissement
    # progressif. La décision ferme est posée à l'autorisation, sur l'ordre de
    # décaissement, et peut différer de cette intention.
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False, default="cash")
    compte_bancaire_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("comptes_bancaires.id"),
        nullable=True,
        index=True,
    )
    rubrique: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    montant_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    budget_poste_code_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_poste_libelle_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    montant_alloue_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    montant_disponible_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
