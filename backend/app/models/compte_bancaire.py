from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CompteBancaire(Base):
    __tablename__ = "comptes_bancaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    banque_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("banques.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    intitule: Mapped[str] = mapped_column(String(200), nullable=False)
    numero_compte: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    solde_initial: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    solde_actuel: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    banque = relationship("Banque", back_populates="comptes_bancaires")
    encaissements = relationship("Encaissement", back_populates="compte_bancaire")
    sorties_fonds = relationship("SortieFonds", back_populates="compte_bancaire")
