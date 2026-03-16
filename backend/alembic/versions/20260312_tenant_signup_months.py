"""Add billing months to tenant signups.

Revision ID: 20260312_tenant_signup_months
Revises: 20260312_saas_core
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_tenant_signup_months"
down_revision = "20260312_saas_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_signups", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.create_index("ix_tenant_signups_organisation_id", "tenant_signups", ["organisation_id"])
    op.create_foreign_key(
        "fk_tenant_signups_organisation_id",
        "tenant_signups",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("tenant_signups", sa.Column("billing_months", sa.Integer(), nullable=True))
    op.execute("UPDATE tenant_signups SET billing_months = 1 WHERE billing_months IS NULL")
    op.alter_column("tenant_signups", "billing_months", nullable=False)


def downgrade() -> None:
    op.drop_column("tenant_signups", "billing_months")
    op.drop_constraint("fk_tenant_signups_organisation_id", "tenant_signups", type_="foreignkey")
    op.drop_index("ix_tenant_signups_organisation_id", table_name="tenant_signups")
    op.drop_column("tenant_signups", "organisation_id")
