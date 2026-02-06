"""ajout budget_ligne_id sur encaissements

Revision ID: 20260205_enc_budget
Revises: 20260205_role_perm
Create Date: 2026-02-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260205_enc_budget"
down_revision = "20260205_role_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissements",
        sa.Column("budget_ligne_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_encaissements_budget_ligne_id",
        "encaissements",
        ["budget_ligne_id"],
    )
    op.create_foreign_key(
        "fk_encaissements_budget_ligne_id",
        "encaissements",
        "budget_lignes",
        ["budget_ligne_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_encaissements_budget_ligne_id", "encaissements", type_="foreignkey")
    op.drop_index("ix_encaissements_budget_ligne_id", table_name="encaissements")
    op.drop_column("encaissements", "budget_ligne_id")
