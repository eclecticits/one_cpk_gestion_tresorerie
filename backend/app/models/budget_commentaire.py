"""Fil de commentaires attaché à une ligne budgétaire.

Le commentaire est ancré sur le **code** du poste, pas sur son id technique :
l'import d'un budget en mode remplacement supprime physiquement tous les
`budget_postes` de l'exercice puis les recrée avec de nouveaux ids
(cf. `_delete_budget_exercise_poste_settings`). Une clé étrangère vers l'id
ferait donc disparaître les justifications au moment précis où l'on retravaille
les montants qu'elles expliquent.

`budget_poste_id` est conservé en simple raccourci de jointure, annulable et
réhydraté après import : il accélère l'affichage mais ne porte jamais l'identité.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetPosteCommentaire(Base):
    __tablename__ = "budget_poste_commentaires"
    __table_args__ = (
        Index(
            "ix_budget_commentaires_ancre",
            "organisation_id",
            "exercice_id",
            "code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exercice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("budget_exercices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # L'ancre métier : survit aux réimports, contrairement à budget_poste_id.
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    # Raccourci de jointure. SET NULL et non CASCADE : la suppression d'un poste
    # ne doit jamais emporter le commentaire, c'est tout l'intérêt de l'ancre.
    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    texte: Mapped[str] = mapped_column(Text, nullable=False)

    # Statut du budget au moment de l'écriture, figé. Une demande de rallonge
    # écrite en brouillon avant le vote ne se lit pas comme une note ajoutée en
    # cours d'exécution : sans cette date métier, le fil perd son sens.
    statut_budget: Mapped[str | None] = mapped_column(String(20), nullable=True)

    auteur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Nom recopié à l'écriture : un utilisateur supprimé ne doit pas rendre
    # anonyme une justification budgétaire déjà versée au dossier.
    auteur_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    # Renseignée seulement si le commentaire a été retouché. Une modification
    # muette laisserait croire à une rédaction d'origine : l'écran affiche
    # « modifié » dès que cette date existe.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
