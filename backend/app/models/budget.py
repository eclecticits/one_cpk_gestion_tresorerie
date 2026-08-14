from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StatutBudget(enum.Enum):
    BROUILLON = "Brouillon"
    VOTE = "Vot\u00e9"
    CLOTURE = "Cl\u00f4tur\u00e9"


class BudgetExercice(Base):
    __tablename__ = "budget_exercices"
    __table_args__ = (UniqueConstraint("organisation_id", "annee", name="uq_budget_exercices_org_annee"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    annee: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    statut: Mapped[StatutBudget] = mapped_column(
        Enum(
            StatutBudget,
            name="statut_budget",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=StatutBudget.BROUILLON,
    )

    # Commentaire général de l'exercice, rendu sous le tableau dans tous les
    # exports budgétaires. Un par vue : le budget des dépenses et celui des
    # recettes ne se justifient pas par les mêmes arguments, et les deux
    # documents sortent séparément.
    commentaire_general_depense: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentaire_general_recette: Mapped[str | None] = mapped_column(Text, nullable=True)

    postes: Mapped[list["BudgetPoste"]] = relationship(
        "BudgetPoste",
        back_populates="exercice",
        cascade="all, delete-orphan",
    )


class BudgetPoste(Base):
    __tablename__ = "budget_postes"
    __table_args__ = (
        Index(
            "uq_budget_postes_org_exercice_code_active",
            "organisation_id",
            "exercice_id",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exercice_id: Mapped[int] = mapped_column(ForeignKey("budget_exercices.id"), nullable=False, index=True)

    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("budget_postes.id"), nullable=True, index=True)
    type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_global: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # Ligne comptée ou non dans les totaux et la synthèse de l'exercice. Un
    # report d'exercice antérieur figure au budget pour mémoire mais n'est pas
    # une recette de l'année : l'inclure fausserait tous les taux. La ligne
    # reste affichée partout, seuls les agrégats l'ignorent — y compris ceux
    # d'un poste parent, sinon exclure une feuille n'aurait aucun effet.
    inclure_dans_calculs: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    montant_prevu: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_engage: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_paye: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    exercice: Mapped[BudgetExercice] = relationship("BudgetExercice", back_populates="postes")
    parent: Mapped["BudgetPoste | None"] = relationship(
        "BudgetPoste",
        remote_side="BudgetPoste.id",
        back_populates="children",
    )
    children: Mapped[list["BudgetPoste"]] = relationship(
        "BudgetPoste",
        back_populates="parent",
    )
