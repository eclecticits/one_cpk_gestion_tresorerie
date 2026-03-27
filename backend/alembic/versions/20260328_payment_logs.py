"""Add payment logs table.

Revision ID: 20260328_payment_logs
Revises: 20260327_org_theme_sidebar
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260328_payment_logs"
down_revision = "20260327_org_theme_sidebar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payment_logs_organisation_id", "payment_logs", ["organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_logs_organisation_id", table_name="payment_logs")
    op.drop_table("payment_logs")
