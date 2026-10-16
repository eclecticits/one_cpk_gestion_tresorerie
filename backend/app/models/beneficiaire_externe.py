from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BeneficiaireExterne(Base):
    """Personne extérieure qui reçoit des fonds : ni expert-comptable, ni personnel.

    Répertoire léger, propre à chaque organisation. Une fiche se crée une fois et
    se retrouve à la sortie suivante : sans elle, le même chauffeur ou fournisseur
    s'écrit de cinq façons et l'on ne sait plus ce qu'il doit encore justifier.
    Le téléphone et l'e-mail sont facultatifs — une personne sans contact reste
    un bénéficiaire, simplement elle ne sera pas prévenue.
    """

    __tablename__ = "beneficiaires_externes"
    __table_args__ = (
        UniqueConstraint("organisation_id", "nom_normalise", name="uq_beneficiaires_externes_org_nom"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Clé de dé-duplication : `normaliser_cle_beneficiaire(nom)`.
    nom_normalise: Mapped[str] = mapped_column(String(200), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Société ou structure représentée, s'il y en a une.
    structure: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BeneficiaireIdentifieMixin:
    """Qui est le bénéficiaire d'une pièce, et comment le joindre.

    Porté par la réquisition et l'ordre de décaissement, là où le bénéficiaire
    est désigné ; la sortie de fonds le reprend au paiement. `beneficiaire`
    (le nom) reste la colonne propre à chaque pièce.
    """

    #: EXPERT | PERSONNEL | UTILISATEUR | EXTERNE ; NULL quand rien n'a été précisé.
    beneficiaire_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    beneficiaire_expert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experts_comptables.id", ondelete="SET NULL"), nullable=True
    )
    beneficiaire_employe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True
    )
    beneficiaire_externe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("beneficiaires_externes.id", ondelete="SET NULL"), nullable=True
    )
    beneficiaire_utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    beneficiaire_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    beneficiaire_telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
