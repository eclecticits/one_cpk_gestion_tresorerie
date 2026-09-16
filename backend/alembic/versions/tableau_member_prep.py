"""Identités et snapshots préparatoires PP/PM du module Tableau.

Migration additive sous la tête du socle multi-source. Elle ne touche à aucun
référentiel officiel et ne crée aucune table CA/assurance/consolidation.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "tableau_member_prep"
down_revision = "20260916_tableau_multisource"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_member_identities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("member_kind", sa.String(10), nullable=False),
        sa.Column("person_kind", sa.String(10), nullable=False),
        sa.Column("classification_status", sa.String(30), nullable=False, server_default="classified"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("first_seen_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("member_kind IN ('EC', 'SEC')", name="ck_tableau_member_identity_kind"),
        sa.CheckConstraint("person_kind IN ('PHYSIQUE', 'MORALE')", name="ck_tableau_member_identity_person_kind"),
    )
    op.create_index("ix_tableau_member_identities_organisation_id", "tableau_member_identities", ["organisation_id"])
    op.create_index("ix_tableau_member_identities_classification_status", "tableau_member_identities", ["classification_status"])
    op.create_index("ix_tableau_member_identity_key", "tableau_member_identities", ["organisation_id", "numero_ordre"])

    op.create_table(
        "tableau_personne_physique_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_row_id", sa.Integer(), sa.ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("sexe", sa.String(20), nullable=True),
        sa.Column("actif", sa.Boolean(), nullable=True),
        sa.Column("date_naissance", sa.Date(), nullable=True),
        sa.Column("telephone", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("ville", sa.String(150), nullable=True),
        sa.Column("statut_source", sa.String(100), nullable=True),
        sa.Column("statut_normalise", sa.String(30), nullable=True),
        sa.Column("numero_impot", sa.String(100), nullable=True),
        sa.Column("assure_synthetique", sa.Boolean(), nullable=True),
        sa.Column("amlco", sa.Boolean(), nullable=True),
        sa.Column("pourcentage_120_for", sa.Numeric(8, 2), nullable=True),
        sa.Column("pourcentage_80_for", sa.Numeric(8, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tableau_pp_snapshot_organisation_id", "tableau_personne_physique_snapshots", ["organisation_id"])
    op.create_index("ix_tableau_pp_snapshot_source_import_id", "tableau_personne_physique_snapshots", ["source_import_id"])
    op.create_index("ix_tableau_pp_snapshot_source_row_id", "tableau_personne_physique_snapshots", ["source_row_id"])
    op.create_index("ix_tableau_pp_snapshot_identity_id", "tableau_personne_physique_snapshots", ["identity_id"])
    op.create_index("ix_tableau_pp_snapshot_date_situation", "tableau_personne_physique_snapshots", ["date_situation"])
    op.create_index("ix_tableau_pp_snapshot_numero_ordre", "tableau_personne_physique_snapshots", ["numero_ordre"])
    op.create_index("ix_tableau_pp_snapshot_lookup", "tableau_personne_physique_snapshots", ["organisation_id", "numero_ordre", "date_situation"])

    op.create_table(
        "tableau_personne_morale_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_row_id", sa.Integer(), sa.ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("societe", sa.String(300), nullable=False),
        sa.Column("telephone", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("ville", sa.String(150), nullable=True),
        sa.Column("numero_impot", sa.String(100), nullable=True),
        sa.Column("cotisation_source", sa.Text(), nullable=True),
        sa.Column("cotisation_normalisee", postgresql.JSONB(), nullable=True),
        sa.Column("solde", sa.Numeric(18, 2), nullable=True),
        sa.Column("assure_synthetique", sa.Boolean(), nullable=True),
        sa.Column("nb_employes", sa.Integer(), nullable=True),
        sa.Column("nb_ec", sa.Integer(), nullable=True),
        sa.Column("nb_sta", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tableau_pm_snapshot_organisation_id", "tableau_personne_morale_snapshots", ["organisation_id"])
    op.create_index("ix_tableau_pm_snapshot_source_import_id", "tableau_personne_morale_snapshots", ["source_import_id"])
    op.create_index("ix_tableau_pm_snapshot_source_row_id", "tableau_personne_morale_snapshots", ["source_row_id"])
    op.create_index("ix_tableau_pm_snapshot_identity_id", "tableau_personne_morale_snapshots", ["identity_id"])
    op.create_index("ix_tableau_pm_snapshot_date_situation", "tableau_personne_morale_snapshots", ["date_situation"])
    op.create_index("ix_tableau_pm_snapshot_numero_ordre", "tableau_personne_morale_snapshots", ["numero_ordre"])
    op.create_index("ix_tableau_pm_snapshot_lookup", "tableau_personne_morale_snapshots", ["organisation_id", "numero_ordre", "date_situation"])


def downgrade() -> None:
    op.drop_index("ix_tableau_pm_snapshot_lookup", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_numero_ordre", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_date_situation", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_identity_id", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_source_row_id", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_source_import_id", table_name="tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pm_snapshot_organisation_id", table_name="tableau_personne_morale_snapshots")
    op.drop_table("tableau_personne_morale_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_lookup", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_numero_ordre", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_date_situation", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_identity_id", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_source_row_id", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_source_import_id", table_name="tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_pp_snapshot_organisation_id", table_name="tableau_personne_physique_snapshots")
    op.drop_table("tableau_personne_physique_snapshots")
    op.drop_index("ix_tableau_member_identity_key", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_classification_status", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_organisation_id", table_name="tableau_member_identities")
    op.drop_table("tableau_member_identities")
