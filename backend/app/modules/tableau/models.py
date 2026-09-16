from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TableauImport(Base):
    __tablename__ = "secretariat_tableau_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="tableau", index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    dossiers: Mapped[list[TableauDossier]] = relationship("TableauDossier", back_populates="import_ref", cascade="all, delete-orphan")
    source_rows: Mapped[list[TableauSourceRow]] = relationship("TableauSourceRow", back_populates="import_ref", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('personnes_physiques', 'personnes_morales', 'chiffres_affaires', 'assurances', 'tableau')",
            name="ck_tableau_import_source_type",
        ),
    )


class TableauSourceRow(Base):
    """Ligne brute d'un import multi-source, avant toute transformation métier."""

    __tablename__ = "tableau_source_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    # La feuille du classeur d'où vient la ligne. Un import multi-feuilles
    # renumérote à chaque onglet : sans elle, deux lignes distinctes portent le
    # même numéro et se heurtent sur la contrainte d'unicité.
    feuille: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalization_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    normalization_errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    business_key_candidate: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        # L'unicité porte sur la feuille autant que sur la ligne : « ligne 5 »
        # n'a de sens que rapporté à son onglet, et c'est ce que l'opérateur lit
        # dans les erreurs d'import.
        UniqueConstraint("import_id", "feuille", "line_number", name="uq_tableau_source_row_line"),
    )

    import_ref: Mapped[TableauImport] = relationship("TableauImport", back_populates="source_rows")


class TableauReferenceSnapshot(Base):
    """Copie immuable du référentiel officiel utilisée comme point de départ."""

    __tablename__ = "tableau_reference_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False, default="experts_comptables")
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, default="NATIONAL", index=True)
    scope_organisation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    scope_definition_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    registry_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("scope_type IN ('NATIONAL', 'EXPLICIT')", name="ck_tableau_reference_scope_type"),
    )


class TableauReferenceMember(Base):
    """Valeurs officielles figées ; l'UUID source reste une preuve, pas une FK."""

    __tablename__ = "tableau_reference_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tableau_reference_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    official_expert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False)
    numero_ordre_normalise: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    province_attache: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    official_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "official_expert_id", name="uq_tableau_reference_member_official"),
        Index("ix_tableau_reference_member_key", "snapshot_id", "numero_ordre_normalise"),
    )


class TableauMemberIdentity(Base):
    """Identité préparatoire interne au module Tableau.

    Cette table ne représente pas le référentiel officiel. Sa FK nullable est
    uniquement un rattachement d'identité en lecture vers celui-ci.
    """

    __tablename__ = "tableau_member_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False)
    numero_ordre_normalise: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    expert_comptable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experts_comptables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    member_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    person_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    classification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="classified", index=True)
    reference_status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNRESOLVED", index=True)
    reference_match_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_match_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    origin_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PP", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    first_seen_import_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_import_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tableau_member_identity_key", "organisation_id", "numero_ordre"),
        Index("ix_tableau_member_identity_normalized_key", "organisation_id", "numero_ordre_normalise"),
        UniqueConstraint("organisation_id", "expert_comptable_id", name="uq_tableau_identity_official_org"),
        CheckConstraint("member_kind IN ('EC', 'SEC')", name="ck_tableau_member_identity_kind"),
        CheckConstraint("person_kind IN ('PHYSIQUE', 'MORALE')", name="ck_tableau_member_identity_person_kind"),
        CheckConstraint(
            "reference_status IN ('MATCHED_OFFICIAL', 'ABSENT_DU_REFERENTIEL', 'AMBIGUOUS', 'UNRESOLVED')",
            name="ck_tableau_identity_reference_status",
        ),
        CheckConstraint("origin_type IN ('OFFICIAL', 'PP', 'PM')", name="ck_tableau_identity_origin_type"),
    )


class TableauPersonnePhysiqueSnapshot(Base):
    __tablename__ = "tableau_personne_physique_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False, index=True)
    identity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True, index=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    nom: Mapped[str] = mapped_column(String(300), nullable=False)
    sexe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actif: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    date_naissance: Mapped[Date | None] = mapped_column(Date, nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ville: Mapped[str | None] = mapped_column(String(150), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    statut_normalise: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cabinet_attache: Mapped[str | None] = mapped_column(String(150), nullable=True)
    numero_impot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nif: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nom_employeur: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assure_synthetique: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    amlco: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pourcentage_120_for: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    pourcentage_80_for: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tableau_pp_snapshot_lookup", "organisation_id", "numero_ordre", "date_situation"),
    )


class TableauPersonneMoraleSnapshot(Base):
    __tablename__ = "tableau_personne_morale_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False, index=True)
    identity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True, index=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    societe: Mapped[str] = mapped_column(String(300), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ville: Mapped[str | None] = mapped_column(String(150), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    numero_impot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cotisation_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    cotisation_normalisee: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    solde: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    assure_synthetique: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nb_employes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nb_ec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nb_sta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tableau_pm_snapshot_lookup", "organisation_id", "numero_ordre", "date_situation"),
    )


class TableauCaDeclaration(Base):
    """Observation historique d'un chiffre d'affaires source."""

    __tablename__ = "tableau_ca_declarations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False, index=True)
    member_identity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True, index=True)
    numero_ordre_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_ordre_normalise: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    membre_libelle_source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    actif_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actif_normalise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    annee: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    devise_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    devise_normalisee: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    ca_facture_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ca_facture: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    ca_collecte_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ca_collecte: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    date_mise_a_jour_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_mise_a_jour: Mapped[Date | None] = mapped_column(Date, nullable=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ca_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tableau_ca_lookup", "organisation_id", "numero_ordre_normalise", "date_situation"),
    )


class TableauInsuranceDeclaration(Base):
    """Déclaration d'assurance historique, indépendante de l'indicateur assuré."""

    __tablename__ = "tableau_insurance_declarations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False, index=True)
    member_identity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True, index=True)
    membre_source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    numero_ordre_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_ordre_normalise: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    declare_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    declare_normalise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    souscrit_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    souscrit_normalise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fin_couverture_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fin_couverture: Mapped[Date | None] = mapped_column(Date, nullable=True)
    annee_souscription_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    annee_souscription: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assureur_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    assureur_normalise: Mapped[str | None] = mapped_column(String(300), nullable=True)
    periode_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    periode_normalisee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tableau_insurance_lookup", "organisation_id", "numero_ordre_normalise", "date_situation"),
    )


class TableauActualisation(Base):
    """Révision matérialisée et immuable d'une situation préparatoire."""

    __tablename__ = "tableau_actualisations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    actualized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    reference_snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tableau_reference_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ruleset_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ruleset_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed", index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organisation_id",
            "date_situation",
            "revision_number",
            name="uq_tableau_actualisation_revision",
        ),
        CheckConstraint("revision_number > 0", name="ck_tableau_actualisation_revision_positive"),
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="ck_tableau_actualisation_status"),
    )


class TableauActualisationInput(Base):
    __tablename__ = "tableau_actualisation_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actualisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tableau_actualisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    import_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    date_situation: Mapped[Date] = mapped_column(Date, nullable=False)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("actualisation_id", "import_id", name="uq_tableau_actualisation_input"),
    )


class TableauActualisationRow(Base):
    __tablename__ = "tableau_actualisation_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actualisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tableau_actualisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tableau_member_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    official_expert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    reference_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    proposal_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    official_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    proposed_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    field_provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    differences_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    anomalies_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("actualisation_id", "identity_id", name="uq_tableau_actualisation_row_identity"),
        CheckConstraint(
            "proposal_status IN ('OFFICIAL_ONLY', 'UNCHANGED', 'UPDATE_PROPOSED', 'CONFLICT', "
            "'NEW_IDENTITY', 'AMBIGUOUS_MATCH', 'BLOCKED')",
            name="ck_tableau_actualisation_proposal_status",
        ),
    )


class TableauDossier(Base):
    __tablename__ = "secretariat_tableau_dossiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    numero_ordre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    prenom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    categorie: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    statut_membre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cotisation_montant: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cotisation_payee: Mapped[bool | None] = mapped_column(nullable=True)
    heures_forco: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    assurance: Mapped[bool | None] = mapped_column(nullable=True)
    chiffre_affaires: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sexe: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_naissance: Mapped[Date | None] = mapped_column(Date, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nif: Mapped[str | None] = mapped_column(String(50), nullable=True)
    anciennete: Mapped[str | None] = mapped_column(String(30), nullable=True)
    annee_inscription: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anciennete_annees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    conclusion_motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    cabinet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    statut_dossier: Mapped[str] = mapped_column(String(30), nullable=False, default="imported", index=True)
    anomalie_detectee: Mapped[bool] = mapped_column(nullable=False, default=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        # Sert la déduplication de la base consolidée (une situation par membre).
        Index("ix_secretariat_tableau_dossiers_base", "organisation_id", "exercice", "numero_ordre"),
    )

    import_ref: Mapped[TableauImport] = relationship("TableauImport", back_populates="dossiers")
    anomalies: Mapped[list[TableauAnomalie]] = relationship("TableauAnomalie", back_populates="dossier", cascade="all, delete-orphan")


class TableauAnalyse(Base):
    __tablename__ = "secretariat_tableau_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="import", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    total_dossiers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dossiers_complets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dossiers_incomplets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalies_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doublons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cotisations_non_payees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heures_forco_insuffisantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assurances_manquantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_dossier_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_import_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_decision_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("organisation_id", "import_id", "scope", name="uq_tableau_analyse_scope"),
    )


class TableauAnomalie(Base):
    __tablename__ = "secretariat_tableau_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    analyse_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("secretariat_tableau_analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    dossier_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True)
    type_anomalie: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    gravite: Mapped[str] = mapped_column(String(20), nullable=False, default="medium", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    champ_concerne: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valeur_trouvee: Mapped[str | None] = mapped_column(String(500), nullable=True)
    valeur_attendue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    dossier: Mapped[TableauDossier] = relationship("TableauDossier", back_populates="anomalies")


class TableauDecision(Base):
    __tablename__ = "secretariat_tableau_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    dossier_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type_decision: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TableauReport(Base):
    __tablename__ = "secretariat_tableau_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    import_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="SET NULL"), nullable=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False)
    type_rapport: Mapped[str] = mapped_column(String(50), nullable=False)
    titre: Mapped[str] = mapped_column(String(300), nullable=False)
    contenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    format_sortie: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class TableauAuditLog(Base):
    """Journal du module : qui a corrigé, décidé, analysé ou interrogé l'assistant.

    Le Tableau tenait sa trace dans le journal du Secrétariat, dont il ne dépend
    plus. Les entrées existantes y ont été reprises par 20260915_tableau_audit.
    """

    __tablename__ = "tableau_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="success", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
