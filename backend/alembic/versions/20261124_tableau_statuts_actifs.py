"""Tableau : statut « Actif » déclaré à la main

Revision ID: 20261124_tableau_statuts_actifs
Revises: 20261124_tableau_deliberations

Seul le fichier des personnes physiques porte une colonne « Actif » : une
société n'avait donc jamais de statut, et un EC mal renseigné ne pouvait pas
être corrigé. La déclaration tient au membre (conseil + n° d'ordre), vaut à
partir de l'exercice de sa date d'effet, et prime sur le fichier. Une seule est
en vigueur par membre ; une annulation la garde dans l'historique.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261124_tableau_statuts_actifs"
down_revision = "20261124_tableau_deliberations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_statuts_actifs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("personne", sa.String(2), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column("actif_fichier", sa.Boolean(), nullable=True),
        sa.Column("date_effet", sa.Date(), nullable=False),
        sa.Column("motif", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("piece_path", sa.String(500), nullable=True),
        sa.Column("piece_nom", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("annule_par", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        sa.CheckConstraint("personne IN ('PP', 'PM')", name="ck_tableau_statut_actif_personne"),
    )
    op.create_index("ix_tableau_statuts_actifs_organisation_id", "tableau_statuts_actifs", ["organisation_id"])
    op.create_index("ix_tableau_statuts_actifs_membre", "tableau_statuts_actifs", ["organisation_id", "numero_ordre"])
    op.create_index(
        "uq_tableau_statut_actif_en_vigueur",
        "tableau_statuts_actifs",
        ["organisation_id", "numero_ordre"],
        unique=True,
        postgresql_where=sa.text("annule_le IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tableau_statut_actif_en_vigueur", table_name="tableau_statuts_actifs")
    op.drop_index("ix_tableau_statuts_actifs_membre", table_name="tableau_statuts_actifs")
    op.drop_index("ix_tableau_statuts_actifs_organisation_id", table_name="tableau_statuts_actifs")
    op.drop_table("tableau_statuts_actifs")
