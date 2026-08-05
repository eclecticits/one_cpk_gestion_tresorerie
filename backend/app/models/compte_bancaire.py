from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CompteBancaire(Base):
    __tablename__ = "comptes_bancaires"
    __table_args__ = (
        CheckConstraint("solde_initial >= 0", name="ck_comptes_bancaires_solde_initial_nonnegative"),
        CheckConstraint("solde_actuel >= 0", name="ck_comptes_bancaires_solde_actuel_nonnegative"),
        UniqueConstraint(
            "organisation_id",
            "banque_id",
            "devise",
            "numero_compte",
            name="uq_comptes_bancaires_org_banque_devise_numero",
        ),
        Index(
            "uq_comptes_bancaires_org_rib",
            "organisation_id",
            "rib",
            unique=True,
            postgresql_where=text("rib IS NOT NULL"),
        ),
        Index(
            "uq_comptes_bancaires_principal_org_devise",
            "organisation_id",
            "devise",
            unique=True,
            postgresql_where=text("is_principal IS TRUE AND account_type = 'BANK'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    banque_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("banques.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    intitule: Mapped[str] = mapped_column(String(200), nullable=False)
    numero_compte: Mapped[str] = mapped_column(String(50), nullable=False)
    rib: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identifiant_client: Mapped[str | None] = mapped_column(String(50), nullable=True)
    code_swift_bic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    compte_comptable_associe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    journal_comptable_associe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_ouverture: Mapped[date | None] = mapped_column(Date, nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    solde_initial: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    solde_actuel: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agence_bancaire: Mapped[str | None] = mapped_column(String(150), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False, default="BANK")

    banque = relationship("Banque", back_populates="comptes_bancaires")
    encaissements = relationship("Encaissement", back_populates="compte_bancaire")
    sorties_fonds = relationship("SortieFonds", back_populates="compte_bancaire")
    organisation = relationship("Organisation")
