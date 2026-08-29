from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: Statuts d'un transfert interne.
#:
#: ``EXECUTE``     — le transfert a déplacé de la trésorerie et compte.
#: ``CONTREPASSE`` — le transfert a été corrigé par un transfert inverse, qui
#:                   est lui-même une ligne ``EXECUTE`` pointant ici via
#:                   ``transfert_origine_id``.
#:
#: **Invariant de lecture : ``statut`` ne filtre JAMAIS une agrégation.** La
#: correction est additive — l'original (−100) et son inverse (+100) coexistent
#: et s'annulent arithmétiquement. Exclure l'original tout en gardant l'inverse
#: donnerait un net de +100, c'est-à-dire de l'argent créé de rien. Le statut
#: sert à l'affichage et au refus d'une seconde contre-passation, pas à décider
#: ce qui entre dans un total. Cf. `clotures.py::_transf_sum` et
#: `reports.py::_sum_transferts`.
STATUT_EXECUTE = "EXECUTE"
STATUT_CONTREPASSE = "CONTREPASSE"
STATUTS_TRANSFERT = (STATUT_EXECUTE, STATUT_CONTREPASSE)


class TransfertInterne(Base):
    __tablename__ = "transferts_internes"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('CAISSE','BANQUE')",
            name="ck_transferts_internes_source_type",
        ),
        CheckConstraint(
            "destination_type IN ('CAISSE','BANQUE')",
            name="ck_transferts_internes_destination_type",
        ),
        CheckConstraint(
            "devise IN ('USD','CDF')",
            name="ck_transferts_internes_devise",
        ),
        CheckConstraint(
            "(source_type = 'CAISSE' AND source_id IS NULL) OR "
            "(source_type = 'BANQUE' AND source_id IS NOT NULL)",
            name="ck_transferts_internes_source_ref",
        ),
        CheckConstraint(
            "(destination_type = 'CAISSE' AND destination_id IS NULL) OR "
            "(destination_type = 'BANQUE' AND destination_id IS NOT NULL)",
            name="ck_transferts_internes_destination_ref",
        ),
        # Une contre-passation est un montant positif source/destination
        # permutées : aucun montant négatif ne circule dans cette table.
        CheckConstraint("montant > 0", name="ck_transferts_internes_montant_positif"),
        CheckConstraint(
            "NOT (source_type = destination_type AND COALESCE(source_id, 0) = COALESCE(destination_id, 0))",
            name="ck_transferts_internes_sources_distinctes",
        ),
        CheckConstraint(
            "statut IN ('EXECUTE', 'CONTREPASSE')",
            name="ck_transferts_internes_statut",
        ),
        # Une contre-passation ne se contre-passe pas : corriger une correction
        # est un nouveau transfert, pas une chaîne d'annulations.
        CheckConstraint(
            "transfert_origine_id IS NULL OR statut = 'EXECUTE'",
            name="ck_transferts_internes_contrepassation_terminale",
        ),
        CheckConstraint(
            "statut <> 'CONTREPASSE' OR ("
            "contrepasse_le IS NOT NULL AND contrepasse_par IS NOT NULL "
            "AND motif_contrepassation IS NOT NULL)",
            name="ck_transferts_internes_contrepassation_complete",
        ),
        Index("uq_transferts_internes_org_idempotency", "organisation_id", "idempotency_key", unique=True, postgresql_where=text("idempotency_key IS NOT NULL")),
        Index("uq_transferts_internes_org_reference", "organisation_id", "reference", unique=True, postgresql_where=text("reference IS NOT NULL")),
        # Au plus une contre-passation par transfert, garanti par la base.
        Index("uq_transferts_internes_origine", "transfert_origine_id", unique=True, postgresql_where=text("transfert_origine_id IS NOT NULL")),
        Index("ix_transferts_internes_org_date", "organisation_id", "date_transfert"),
        Index("ix_transferts_internes_org_statut", "organisation_id", "statut"),
        Index("ix_transferts_internes_org_reference", "organisation_id", "reference"),
        # Identité documentaire : le frontend et la route d'envoi du bon
        # adressent une opération par UUID. Unique, partiel — seuls les
        # transferts saisis par le chemin `sorties-fonds` en portent un.
        Index("uq_transferts_internes_document_uuid", "document_uuid", unique=True,
              postgresql_where=text("document_uuid IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_type: Mapped[str] = mapped_column(String(10), nullable=False)
    destination_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_transfert: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    execute_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUT_EXECUTE)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Renseignés sur le transfert d'ORIGINE au moment où il est contre-passé.
    contrepasse_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contrepasse_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    motif_contrepassation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Renseigné sur la ligne INVERSE, et pointe vers le transfert corrigé.
    transfert_origine_id: Mapped[int | None] = mapped_column(ForeignKey("transferts_internes.id", ondelete="RESTRICT"), nullable=True)
    #: Identité documentaire d'un transfert saisi via `POST /sorties-fonds`.
    #:
    #: Le frontend reçoit une sortie de fonds et s'en sert pour lui attacher le
    #: bon imprimé (`POST /sorties-fonds/{id}/pdf`). Il attend un UUID ; la clé
    #: primaire d'un transfert est un entier. Cette colonne porte donc l'UUID
    #: que ce chemin annonce, et permet de retrouver le transfert à partir de
    #: lui. NULL pour un transfert créé directement sur `/transferts-internes`,
    #: qui n'a jamais annoncé d'UUID à personne.
    document_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: Le bon signé, quand il y en a un. Même sémantique que
    #: `SortieFonds.pdf_path` : un chemin servi derrière `/uploads`.
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Pièces jointes (bordereau de dépôt, avis bancaire). Sans elles, basculer
    #: un versement ferait disparaître en silence le justificatif que le
    #: caissier joint aujourd'hui.
    annexes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
