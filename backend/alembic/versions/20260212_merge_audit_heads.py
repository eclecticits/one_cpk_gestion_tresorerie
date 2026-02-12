"""merge audit_logs and budget heads

Revision ID: 20260212_merge_audit_heads
Revises: 20260211_budget_2027_2026, 20260212_audit_logs
Create Date: 2026-02-12
"""

from alembic import op


revision = "20260212_merge_audit_heads"
down_revision = ("20260211_budget_2027_2026", "20260212_audit_logs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
