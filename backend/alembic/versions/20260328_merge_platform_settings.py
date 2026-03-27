"""merge platform settings head

Revision ID: 20260328_merge_platform_settings
Revises: 20260328_saas_checkout_core, 20260328_platform_settings
Create Date: 2026-03-28 22:45:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260328_merge_platform_settings"
down_revision = ("20260328_saas_checkout_core", "20260328_platform_settings")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
