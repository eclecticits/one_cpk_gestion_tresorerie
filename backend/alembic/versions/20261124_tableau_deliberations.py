"""Tableau : délibérations de la commission sur un membre

Revision ID: 20261124_tableau_deliberations
Revises: 20261123_tableau_reglages

La délibération tient au membre (conseil + n° d'ordre) pour un exercice, comme
la sortie : elle vaut pour les EC et les sociétés, avec ou sans dossier, et un
réimport ne la fait pas disparaître. Une seule délibération en vigueur par
membre et par exercice ; une révocation la garde dans l'historique.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261124_tableau_deliberations"
down_revision = "20261123_tableau_reglages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_deliberations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exercice", sa.String(20), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("personne", sa.String(2), nullable=False),
        sa.Column("conclusion", sa.String(30), nullable=False),
        sa.Column("conclusion_automatique", sa.String(30), nullable=True),
        sa.Column("criteres", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("motif", sa.Text(), nullable=False),
        sa.Column("reference_seance", sa.String(200), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("piece_path", sa.String(500), nullable=True),
        sa.Column("piece_nom", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoquee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoquee_par", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("motif_revocation", sa.Text(), nullable=True),
        sa.CheckConstraint("personne IN ('PP', 'PM')", name="ck_tableau_deliberation_personne"),
        sa.CheckConstraint(
            "conclusion IN ('INSCRIT', 'NON INSCRIT', 'À DÉLIBÉRER')",
            name="ck_tableau_deliberation_conclusion",
        ),
    )
    op.create_index("ix_tableau_deliberations_organisation_id", "tableau_deliberations", ["organisation_id"])
    op.create_index(
        "ix_tableau_deliberations_membre", "tableau_deliberations", ["organisation_id", "exercice", "numero_ordre"],
    )
    op.create_index(
        "uq_tableau_deliberation_en_vigueur",
        "tableau_deliberations",
        ["organisation_id", "exercice", "numero_ordre"],
        unique=True,
        postgresql_where=sa.text("revoquee_le IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tableau_deliberation_en_vigueur", table_name="tableau_deliberations")
    op.drop_index("ix_tableau_deliberations_membre", table_name="tableau_deliberations")
    op.drop_index("ix_tableau_deliberations_organisation_id", table_name="tableau_deliberations")
    op.drop_table("tableau_deliberations")
