"""Add SaaS billing config + transactions.

Revision ID: 20260328_saas_checkout_core
Revises: 20260328_merge_payment_logs
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260328_saas_checkout_core"
down_revision = "20260328_merge_payment_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organisations", sa.Column("billing_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("status", sa.Enum("pending", "success", "failed", "expired", name="paymentstatus"), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=True),
        sa.Column("external_reference", sa.String(length=120), nullable=True, unique=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_tenant_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_column("organisations", "billing_config")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
