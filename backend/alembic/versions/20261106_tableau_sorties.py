"""Tableau : sorties des membres (décès, démission, radiation, omission, cessation)

Revision ID: 20261106_tableau_sorties
Revises: 20261106_nd_rattachements

La sortie n'est pas une catégorie : elle tient au membre (conseil + n° d'ordre)
et vaut pour les exercices à partir de l'année de sa date d'effet.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261106_tableau_sorties"
down_revision = "20261106_nd_rattachements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_sorties_membres",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("personne", sa.String(2), nullable=False),
        sa.Column("situation", sa.String(20), nullable=False),
        sa.Column("date_effet", sa.Date(), nullable=False),
        sa.Column("lieu_deces", sa.String(200), nullable=True),
        sa.Column("motif_cessation", sa.String(20), nullable=True),
        sa.Column("societe_absorbante", sa.String(300), nullable=True),
        sa.Column("reference_decision", sa.String(200), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("piece_path", sa.String(500), nullable=True),
        sa.Column("piece_nom", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "numero_ordre", name="uq_tableau_sortie_membre"),
        sa.CheckConstraint("personne IN ('PP', 'PM')", name="ck_tableau_sortie_personne"),
        sa.CheckConstraint(
            "situation IN ('DECEDE', 'DEMISSIONNAIRE', 'RADIE', 'OMIS', 'CESSE')",
            name="ck_tableau_sortie_situation",
        ),
    )
    op.create_index("ix_tableau_sorties_membres_organisation_id", "tableau_sorties_membres", ["organisation_id"])
    op.create_index("ix_tableau_sorties_membres_situation", "tableau_sorties_membres", ["situation"])


def downgrade() -> None:
    op.drop_index("ix_tableau_sorties_membres_situation", table_name="tableau_sorties_membres")
    op.drop_index("ix_tableau_sorties_membres_organisation_id", table_name="tableau_sorties_membres")
    op.drop_table("tableau_sorties_membres")
