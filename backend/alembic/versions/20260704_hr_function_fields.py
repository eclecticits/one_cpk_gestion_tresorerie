"""hr functions: code, description, niveau_hierarchique

Revision ID: 20260704_hr_function_fields
Revises: 20260703_hr_service_hierarchy
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260704_hr_function_fields"
down_revision = "20260703_hr_service_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_functions", sa.Column("code", sa.String(length=30), nullable=True))
    op.add_column("hr_functions", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("hr_functions", sa.Column("niveau_hierarchique", sa.String(length=100), nullable=True))

    op.execute("UPDATE hr_functions SET code = 'FN-' || id::text WHERE code IS NULL")

    op.alter_column("hr_functions", "code", nullable=False)
    op.create_unique_constraint("uq_hr_functions_tenant_code", "hr_functions", ["tenant_id", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_hr_functions_tenant_code", "hr_functions", type_="unique")

    op.drop_column("hr_functions", "niveau_hierarchique")
    op.drop_column("hr_functions", "description")
    op.drop_column("hr_functions", "code")
