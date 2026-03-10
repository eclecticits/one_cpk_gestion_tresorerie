"""Merge heads after tenant settings.

Revision ID: 20260310_merge_tenant_heads
Revises: 20260306_payment_tx, 20260310_tenant_settings
Create Date: 2026-03-10
"""

from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = "20260310_merge_tenant_heads"
down_revision = ("20260306_payment_tx", "20260310_tenant_settings")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
