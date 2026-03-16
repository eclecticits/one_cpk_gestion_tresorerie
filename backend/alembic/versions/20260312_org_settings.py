"""Add organisation settings for provisioning dependencies.

Revision ID: 20260312_org_settings
Revises: 20260312_tenant_signup_months
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_org_settings"
down_revision = "20260312_tenant_signup_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organisation_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("storage_limit_gb", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enable_ai_analysis", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enable_mobile_payments", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("fiscal_year_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("currency_code", sa.String(length=10), nullable=False, server_default="CDF"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_organisation_settings_org_id", "organisation_settings", ["organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_organisation_settings_org_id", table_name="organisation_settings")
    op.drop_table("organisation_settings")
