from __future__ import annotations

import enum
from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StatutBudget(enum.Enum):
    BROUILLON = "Brouillon"
    VOTE = "Vot\u00e9"
    CLOTURE = "Cl\u00f4tur\u00e9"


class BudgetExercice(Base):
    __tablename__ = "budget_exercices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    annee: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    statut: Mapped[StatutBudget] = mapped_column(
        Enum(
            StatutBudget,
            name="statut_budget",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=StatutBudget.BROUILLON,
    )

    lignes: Mapped[list["BudgetLigne"]] = relationship(
        "BudgetLigne",
        back_populates="exercice",
        cascade="all, delete-orphan",
    )


class BudgetLigne(Base):
    __tablename__ = "budget_lignes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exercice_id: Mapped[int] = mapped_column(ForeignKey("budget_exercices.id"), nullable=False, index=True)

    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    montant_prevu: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_engage: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_paye: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)

    exercice: Mapped[BudgetExercice] = relationship("BudgetExercice", back_populates="lignes")
