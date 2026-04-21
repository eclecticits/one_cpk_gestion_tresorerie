"""Add SaaS invoices and renewal alert tracking.

Revision ID: 20260421_saas_invoices_alerts
Revises: 20260421_payment_flow_split
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260421_saas_invoices_alerts"
down_revision = "20260421_payment_flow_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saas_invoices",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("invoice_number", sa.String(length=60), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PAID"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("invoice_number", name="uq_saas_invoices_invoice_number"),
        sa.UniqueConstraint("transaction_id", name="uq_saas_invoices_transaction_id"),
    )
    op.create_index("ix_saas_invoices_invoice_number", "saas_invoices", ["invoice_number"])
    op.create_index("ix_saas_invoices_organisation_id", "saas_invoices", ["organisation_id"])
    op.create_index("ix_saas_invoices_subscription_id", "saas_invoices", ["subscription_id"])
    op.create_index("ix_saas_invoices_transaction_id", "saas_invoices", ["transaction_id"])

    op.add_column("subscriptions", sa.Column("renewal_alert_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("renewal_alert_period_end", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "renewal_alert_period_end")
    op.drop_column("subscriptions", "renewal_alert_sent_at")
    op.drop_index("ix_saas_invoices_transaction_id", table_name="saas_invoices")
    op.drop_index("ix_saas_invoices_subscription_id", table_name="saas_invoices")
    op.drop_index("ix_saas_invoices_organisation_id", table_name="saas_invoices")
    op.drop_index("ix_saas_invoices_invoice_number", table_name="saas_invoices")
    op.drop_table("saas_invoices")
