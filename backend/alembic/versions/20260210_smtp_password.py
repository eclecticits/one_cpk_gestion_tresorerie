"""add smtp_password to system_settings

Revision ID: 20260210_smtp_password
Revises: 20260210_system_settings
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260210_smtp_password"
down_revision = "20260210_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("smtp_password", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "smtp_password")
