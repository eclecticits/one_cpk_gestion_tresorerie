"""Notes de débit : rattachement des colonnes de la situation au budget

Revision ID: 20261106_nd_rattachements
Revises: 20261105_avance_reportee

Chaque colonne de la situation des membres (cotisations et pénalités ≤ N-1,
cotisation et pénalités N, autres créances) se rattache à un poste de recette,
désigné par son code, éventuellement par catégorie de membre.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261106_nd_rattachements"
down_revision = "20261105_avance_reportee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes_debit_rattachements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("colonne", sa.String(40), nullable=False),
        sa.Column("categorie_membre", sa.String(40), nullable=False, server_default="*"),
        sa.Column("budget_poste_code", sa.String(50), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "colonne", "categorie_membre", name="uq_note_debit_rattachement"),
    )
    op.create_index(
        "ix_notes_debit_rattachements_organisation_id", "notes_debit_rattachements", ["organisation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notes_debit_rattachements_organisation_id", table_name="notes_debit_rattachements")
    op.drop_table("notes_debit_rattachements")
