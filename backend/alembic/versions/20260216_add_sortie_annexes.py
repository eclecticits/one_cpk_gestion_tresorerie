"""add annexes to sorties_fonds

Revision ID: 20260216_sortie_annex
Revises: 20260216_fix_audit_ip
Create Date: 2026-02-16
"""

from alembic import op


revision = "20260216_sortie_annex"
down_revision = "20260216_fix_audit_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sorties_fonds ADD COLUMN IF NOT EXISTS annexes JSONB;")


def downgrade() -> None:
    # no-op
    pass
