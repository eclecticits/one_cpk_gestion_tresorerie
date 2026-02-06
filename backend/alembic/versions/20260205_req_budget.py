"""ajout budget_ligne_id sur lignes_requisition

Revision ID: 20260205_req_budget
Revises: 20260205_budget_module
Create Date: 2026-02-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260205_req_budget"
down_revision = "20260205_budget_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lignes_requisition",
        sa.Column("budget_ligne_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_lignes_requisition_budget_ligne_id",
        "lignes_requisition",
        ["budget_ligne_id"],
    )
    op.create_foreign_key(
        "fk_lignes_requisition_budget_ligne_id",
        "lignes_requisition",
        "budget_lignes",
        ["budget_ligne_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_lignes_requisition_budget_ligne_id", "lignes_requisition", type_="foreignkey")
    op.drop_index("ix_lignes_requisition_budget_ligne_id", table_name="lignes_requisition")
    op.drop_column("lignes_requisition", "budget_ligne_id")
