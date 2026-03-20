"""Add is_global flag to budget_postes.

Revision ID: 20260324_budget_poste_is_global
Revises: 20260323_seed_initial_organisations
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_budget_poste_is_global"
down_revision = "20260323_seed_initial_organisations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_postes",
        sa.Column("is_global", sa.Boolean(), nullable=True, server_default=sa.text("FALSE")),
    )
    op.create_index("ix_budget_postes_is_global", "budget_postes", ["is_global"])
    op.execute("UPDATE budget_postes SET is_global = FALSE WHERE is_global IS NULL")
    op.alter_column("budget_postes", "is_global", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_budget_postes_is_global", table_name="budget_postes")
    op.drop_column("budget_postes", "is_global")
