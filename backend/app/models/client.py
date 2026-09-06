from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Client(Base):
    """Client de l'organisation (hors experts-comptables, qui ont leur table).

    Référentiel unique des clients externes / institutions / partenaires,
    alimenté depuis les encaissements. Évite les doublons : le nom est
    unique (insensible à la casse) par organisation, et la saisie propose
    les clients existants (autocomplétion).
    """

    __tablename__ = "clients"
    __table_args__ = (
        # 'M' ou 'F', ou rien. La contrainte vaut pour toutes les fiches, y
        # compris celles qu'aucun formulaire ne renseigne : une organisation
        # n'a pas de sexe, et NULL est la seule façon de le dire.
        CheckConstraint("sexe IS NULL OR sexe IN ('M', 'F')", name="ck_clients_sexe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    nom: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    # Type indicatif (dernier type utilisé) : client_externe, banque_institution,
    # partenaire, organisation, autre.
    type_client: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Sexe de la personne, 'M' ou 'F'. Porté par la FICHE et non par
    # l'encaissement : c'est un trait de la personne, pas de l'opération, et il
    # n'aurait aucune raison de changer d'un versement à l'autre. Le formulaire
    # ne le propose que là où il veut dire quelque chose — personne physique et
    # client externe ; les banques, institutions et organisations le laissent à
    # NULL.
    sexe: Mapped[str | None] = mapped_column(String(1), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# Unicité insensible à la casse du nom par organisation (anti-doublons).
Index(
    "uq_clients_org_nom_lower",
    Client.organisation_id,
    func.lower(Client.nom),
    unique=True,
)
