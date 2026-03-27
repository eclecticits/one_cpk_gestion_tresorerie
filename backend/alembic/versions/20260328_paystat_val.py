"""add validation payment status

Revision ID: 20260328_paystat_val
Revises: 20260328_merge_platform_settings
Create Date: 2026-03-28 23:12:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260328_paystat_val"
down_revision = "20260328_merge_platform_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'validation'")


def downgrade() -> None:
    pass
