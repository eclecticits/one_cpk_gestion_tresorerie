"""Merge heads: payment logs and docseq tenant.

Revision ID: 20260328_merge_payment_logs
Revises: 20260327_docseq_tenant, 20260328_payment_logs
Create Date: 2026-03-28
"""

from alembic import op


revision = "20260328_merge_payment_logs"
down_revision = ("20260327_docseq_tenant", "20260328_payment_logs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
