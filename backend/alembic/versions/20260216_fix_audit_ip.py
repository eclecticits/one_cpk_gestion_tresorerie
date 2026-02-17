"""ensure audit_logs ip_address column exists

Revision ID: 20260216_fix_audit_ip
Revises: 20260216_fix_audit
Create Date: 2026-02-16
"""

from alembic import op


revision = "20260216_fix_audit_ip"
down_revision = "20260216_fix_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64);")


def downgrade() -> None:
    # no-op
    pass
