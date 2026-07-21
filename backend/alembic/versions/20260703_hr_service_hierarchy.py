"""hr services: description, responsable, parent hierarchy

Revision ID: 20260703_hr_service_hierarchy
Revises: 20260702_hr_payroll_settings
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260703_hr_service_hierarchy"
down_revision = "20260702_hr_payroll_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_services", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("hr_services", sa.Column("responsable_id", sa.Integer(), nullable=True))
    op.add_column("hr_services", sa.Column("parent_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_hr_services_responsable_id",
        "hr_services",
        "hr_employees",
        ["responsable_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_hr_services_parent_id",
        "hr_services",
        "hr_services",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(op.f("ix_hr_services_responsable_id"), "hr_services", ["responsable_id"], unique=False)
    op.create_index(op.f("ix_hr_services_parent_id"), "hr_services", ["parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_hr_services_parent_id"), table_name="hr_services")
    op.drop_index(op.f("ix_hr_services_responsable_id"), table_name="hr_services")

    op.drop_constraint("fk_hr_services_parent_id", "hr_services", type_="foreignkey")
    op.drop_constraint("fk_hr_services_responsable_id", "hr_services", type_="foreignkey")

    op.drop_column("hr_services", "parent_id")
    op.drop_column("hr_services", "responsable_id")
    op.drop_column("hr_services", "description")
