from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FondsTiersOperation(Base):
    """Suivi métier d'un fonds reçu pour compte de tiers.

    Le flux financier reste porté par encaissements/sorties_fonds. Cette table
    ne duplique pas la trésorerie ; elle relie l'entrée d'origine à ses
    remboursements et porte les informations propres au tiers.
    """

    __tablename__ = "fonds_tiers_operations"
    __table_args__ = (
        CheckConstraint(
            "statut IN ('OUVERT','PARTIELLEMENT_REMBOURSE','REGULARISE','ANNULE')",
            name="ck_fonds_tiers_statut",
        ),
        CheckConstraint(
            """
            (
                tiers_organisation_id IS NOT NULL
                AND tiers_nom_libre IS NULL
            )
            OR (
                tiers_organisation_id IS NULL
                AND tiers_nom_libre IS NOT NULL
                AND btrim(tiers_nom_libre) <> ''
            )
            OR (
                tiers_organisation_id IS NULL
                AND tiers_nom_libre IS NULL
                AND tiers_concerne IS NOT NULL
                AND btrim(tiers_concerne) <> ''
            )
            """,
            name="ck_fonds_tiers_tiers_source",
        ),
        UniqueConstraint("organisation_id", "encaissement_id", name="uq_fonds_tiers_org_encaissement"),
        Index("ix_fonds_tiers_org_statut", "organisation_id", "statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    encaissement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=False, index=True)
    statut: Mapped[str] = mapped_column(String(40), nullable=False, default="OUVERT", index=True)
    tiers_concerne: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tiers_organisation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    tiers_nom_libre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payeur_origine: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Historique, en lecture seule : plus aucun chemin ne l'écrit depuis que le
    # tiers est le seul bénéficiaire d'un reversement. Conservé parce que des
    # opérations antérieures en portent la valeur et que l'écran des fonds de
    # tiers l'affiche encore ; à supprimer quand ces lignes auront été soldées.
    beneficiaire_reel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annulee_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)

    encaissement = relationship("Encaissement")
    # Deux clés étrangères pointent vers `organisations` — celle qui détient les
    # fonds et celle pour qui ils sont détenus. Le chemin doit donc être nommé
    # explicitement, sans quoi la configuration des mappers échoue.
    organisation = relationship("Organisation", foreign_keys=[organisation_id])
    # Pas de relation vers le tiers : `_apply_tenant_criteria` scope toute
    # lecture d'`Organisation` au tenant courant, et le tiers est par définition
    # une autre organisation — la relation résoudrait donc toujours None.
    # Passer par `resolve_fonds_tiers_display_name(s)`, qui lève le scope.
