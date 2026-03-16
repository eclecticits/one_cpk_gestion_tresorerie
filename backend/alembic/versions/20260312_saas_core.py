"""SaaS core: plans, subscriptions, tenant signups.

Revision ID: 20260312_saas_core
Revises: 20260312_budget_payments_tenant
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260312_saas_core"
down_revision = "20260312_budget_payments_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("monthly_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("name", name="uq_plans_name"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fedapay_transaction_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_subscriptions_organisation_id", "subscriptions", ["organisation_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_fedapay_transaction_id", "subscriptions", ["fedapay_transaction_id"])

    op.create_table(
        "tenant_signups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organisation_name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("admin_email", sa.String(length=255), nullable=False),
        sa.Column("admin_phone", sa.String(length=50), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending_payment"),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("fedapay_transaction_id", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reference", name="uq_tenant_signups_reference"),
    )
    op.create_index("ix_tenant_signups_slug", "tenant_signups", ["slug"])
    op.create_index("ix_tenant_signups_admin_email", "tenant_signups", ["admin_email"])
    op.create_index("ix_tenant_signups_plan_id", "tenant_signups", ["plan_id"])
    op.create_index("ix_tenant_signups_fedapay_transaction_id", "tenant_signups", ["fedapay_transaction_id"])

    op.execute(
        """
        INSERT INTO plans (name, monthly_price, features, is_active)
        VALUES
            ('Essentiel', 0, '{"max_users": 5, "ai_reports": false}', true),
            ('Premium', 99, '{"max_users": 20, "ai_reports": true}', true),
            ('Expert', 199, '{"max_users": 50, "ai_reports": true}', true)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_signups_fedapay_transaction_id", table_name="tenant_signups")
    op.drop_index("ix_tenant_signups_plan_id", table_name="tenant_signups")
    op.drop_index("ix_tenant_signups_admin_email", table_name="tenant_signups")
    op.drop_index("ix_tenant_signups_slug", table_name="tenant_signups")
    op.drop_table("tenant_signups")

    op.drop_index("ix_subscriptions_fedapay_transaction_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_organisation_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_table("plans")
