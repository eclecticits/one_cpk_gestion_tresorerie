"""Align SaaS columns (plans, organisation settings, subscriptions).

Revision ID: 20260313_saas_alignment
Revises: 20260312_tenant_signup_months
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260313_saas_alignment"
down_revision = "20260312_org_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plans") as batch:
        batch.add_column(sa.Column("max_users", sa.Integer(), nullable=False, server_default="10"))
        batch.add_column(sa.Column("ai_features_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.alter_column(
            "monthly_price",
            new_column_name="monthly_price_usd",
            existing_type=sa.Numeric(10, 2),
        )
    op.alter_column("plans", "monthly_price_usd", server_default="0", existing_type=sa.Numeric(10, 2))

    with op.batch_alter_table("organisation_settings") as batch:
        batch.alter_column("enable_ai_analysis", new_column_name="is_ai_enabled", existing_type=sa.Boolean())
        batch.alter_column(
            "enable_mobile_payments",
            new_column_name="is_mobile_money_enabled",
            existing_type=sa.Boolean(),
        )
        batch.alter_column("storage_limit_gb", new_column_name="storage_quota_mb", existing_type=sa.Integer())
        batch.add_column(
            sa.Column("is_audit_logs_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true"))
        )
    op.execute("UPDATE organisation_settings SET storage_quota_mb = storage_quota_mb * 1024")
    op.alter_column("organisation_settings", "storage_quota_mb", server_default="1024", existing_type=sa.Integer())

    op.execute("UPDATE subscriptions SET status = UPPER(status) WHERE status IS NOT NULL")
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'PENDING_PAYMENT'
        WHERE status IN ('PENDING', 'PENDING_PAYMENT', 'EN_ATTENTE', 'EN_ATTENTE_PAIEMENT')
        """
    )
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'ACTIVE'
        WHERE status IN ('ACTIVE', 'ENABLED', 'PAYE', 'PAYÉ')
        """
    )
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'TRIAL'
        WHERE status IN ('TRIALING', 'TRIAL')
        """
    )
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'SUSPENDED'
        WHERE status IN ('PAST_DUE', 'SUSPENDED', 'CANCELED', 'CANCELLED')
        """
    )
    op.alter_column("subscriptions", "status", server_default="PENDING_PAYMENT", existing_type=sa.String(length=20))


def downgrade() -> None:
    op.alter_column("subscriptions", "status", server_default="pending", existing_type=sa.String(length=20))
    op.execute(
        """
        UPDATE subscriptions
        SET status = CASE
            WHEN status = 'ACTIVE' THEN 'active'
            WHEN status = 'TRIAL' THEN 'trialing'
            WHEN status = 'SUSPENDED' THEN 'past_due'
            WHEN status = 'PENDING_PAYMENT' THEN 'pending'
            ELSE 'pending'
        END
        """
    )

    op.alter_column("organisation_settings", "storage_quota_mb", server_default="1", existing_type=sa.Integer())
    op.execute("UPDATE organisation_settings SET storage_quota_mb = CEIL(storage_quota_mb / 1024.0)")
    with op.batch_alter_table("organisation_settings") as batch:
        batch.drop_column("is_audit_logs_enabled")
        batch.alter_column("storage_quota_mb", new_column_name="storage_limit_gb", existing_type=sa.Integer())
        batch.alter_column(
            "is_mobile_money_enabled",
            new_column_name="enable_mobile_payments",
            existing_type=sa.Boolean(),
        )
        batch.alter_column("is_ai_enabled", new_column_name="enable_ai_analysis", existing_type=sa.Boolean())

    op.alter_column("plans", "monthly_price_usd", server_default="0", existing_type=sa.Numeric(10, 2))
    with op.batch_alter_table("plans") as batch:
        batch.alter_column(
            "monthly_price_usd",
            new_column_name="monthly_price",
            existing_type=sa.Numeric(10, 2),
        )
        batch.drop_column("ai_features_enabled")
        batch.drop_column("max_users")
