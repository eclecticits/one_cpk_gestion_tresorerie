"""add platform settings

Revision ID: 20260328_platform_settings
Revises: 20260328_merge_payment_logs
Create Date: 2026-03-28 22:40:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260328_platform_settings"
down_revision = "20260328_merge_payment_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("billing_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("INSERT INTO platform_settings (id, updated_at) VALUES (1, NOW())")


def downgrade() -> None:
    op.drop_table("platform_settings")
