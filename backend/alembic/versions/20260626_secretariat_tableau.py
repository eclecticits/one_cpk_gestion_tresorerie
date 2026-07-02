"""Add secretariat tableau tables (Agent Tableau)

Revision ID: 20260626_secretariat_tableau
Revises: goauth_uri_enabled
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260626_secretariat_tableau"
down_revision = "goauth_uri_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secretariat_tableau_imports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exercice", sa.String(20), nullable=False, index=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "secretariat_tableau_dossiers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("exercice", sa.String(20), nullable=False, index=True),
        sa.Column("numero_ordre", sa.String(50), nullable=True),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("prenom", sa.String(200), nullable=True),
        sa.Column("categorie", sa.String(50), nullable=False, index=True),
        sa.Column("statut_membre", sa.String(50), nullable=True),
        sa.Column("cotisation_montant", sa.Numeric(14, 2), nullable=True),
        sa.Column("cotisation_payee", sa.Boolean(), nullable=True),
        sa.Column("heures_forco", sa.Numeric(8, 2), nullable=True),
        sa.Column("assurance", sa.Boolean(), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("telephone", sa.String(50), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("cabinet", sa.String(200), nullable=True),
        sa.Column("statut_dossier", sa.String(30), nullable=False, server_default="imported", index=True),
        sa.Column("anomalie_detectee", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "secretariat_tableau_analyses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("exercice", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
        sa.Column("total_dossiers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dossiers_complets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dossiers_incomplets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anomalies_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("doublons_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cotisations_non_payees", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heures_forco_insuffisantes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assurances_manquantes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_ia", sa.Text(), nullable=True),
        sa.Column("stats_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "secretariat_tableau_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("dossier_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type_anomalie", sa.String(80), nullable=False, index=True),
        sa.Column("gravite", sa.String(20), nullable=False, server_default="medium", index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("champ_concerne", sa.String(100), nullable=True),
        sa.Column("valeur_trouvee", sa.String(500), nullable=True),
        sa.Column("valeur_attendue", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="open", index=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "secretariat_tableau_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("dossier_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type_decision", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "secretariat_tableau_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("exercice", sa.String(20), nullable=False),
        sa.Column("type_rapport", sa.String(50), nullable=False),
        sa.Column("titre", sa.String(300), nullable=False),
        sa.Column("contenu", sa.Text(), nullable=True),
        sa.Column("format_sortie", sa.String(20), nullable=False, server_default="text"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("secretariat_tableau_reports")
    op.drop_table("secretariat_tableau_decisions")
    op.drop_table("secretariat_tableau_anomalies")
    op.drop_table("secretariat_tableau_analyses")
    op.drop_table("secretariat_tableau_dossiers")
    op.drop_table("secretariat_tableau_imports")
