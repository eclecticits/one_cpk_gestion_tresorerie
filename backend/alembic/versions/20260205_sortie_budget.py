"""ajout budget_ligne_id sur sorties_fonds

Revision ID: 20260205_sortie_budget
Revises: 20260205_enc_budget
Create Date: 2026-02-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260205_sortie_budget"
down_revision = "20260205_enc_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sorties_fonds",
        sa.Column("budget_ligne_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_sorties_fonds_budget_ligne_id",
        "sorties_fonds",
        ["budget_ligne_id"],
    )
    op.create_foreign_key(
        "fk_sorties_fonds_budget_ligne_id",
        "sorties_fonds",
        "budget_lignes",
        ["budget_ligne_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_sorties_fonds_budget_ligne_id", "sorties_fonds", type_="foreignkey")
    op.drop_index("ix_sorties_fonds_budget_ligne_id", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "budget_ligne_id")
