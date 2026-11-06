"""Rattachement des colonnes de la situation des notes de débit au budget.

La situation des membres range chaque créance dans une colonne : cotisations
et pénalités antérieures à N, cotisation et pénalités de N, autres créances.
Chaque colonne doit tomber sur un poste de recette, pour que chaque paiement
se lise poste par poste. La cotisation de N n'a pas un poste unique : le budget
en porte un par catégorie de membre (EC en cabinet, indépendant, salarié,
société). Un rattachement vaut donc pour une colonne et, au besoin, une
catégorie ; la catégorie « * » couvre toutes celles qui n'ont pas le leur.

Le poste est désigné par son **code**, comme pour les tarifs : les postes sont
recréés à chaque exercice, le code les retrouve d'une année à l'autre.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoteDebitRattachement(Base):
    __tablename__ = "notes_debit_rattachements"
    __table_args__ = (
        UniqueConstraint("organisation_id", "colonne", "categorie_membre", name="uq_note_debit_rattachement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: cotisations_anterieures, penalites_anterieures, cotisation_n, penalites_n, autres_creances
    colonne: Mapped[str] = mapped_column(String(40), nullable=False)
    #: EC Cabinet, EC Indépendant, EC Salarié, Société, ou « * » pour toutes.
    categorie_membre: Mapped[str] = mapped_column(String(40), nullable=False, default="*")
    budget_poste_code: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
