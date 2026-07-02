"""Add ipr and cnss_salarie columns to hr_salary_slips

Revision ID: 20260702_hr_ipr_cnss
Revises: 20260626_secretariat_tableau
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260702_hr_ipr_cnss"
down_revision = "20260626_secretariat_tableau"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hr_salary_slips",
        sa.Column("ipr", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "hr_salary_slips",
        sa.Column("cnss_salarie", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.alter_column("hr_salary_slips", "ipr", server_default=None)
    op.alter_column("hr_salary_slips", "cnss_salarie", server_default=None)


def downgrade() -> None:
    op.drop_column("hr_salary_slips", "cnss_salarie")
    op.drop_column("hr_salary_slips", "ipr")
