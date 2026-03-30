"""add whatsapp settings

Revision ID: 20260330_whatsapp_settings
Revises: 20260330_recu_numero_per_tenant
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20260330_whatsapp_settings"
down_revision = "20260330_recu_numero_per_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("whatsapp_api_url", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("whatsapp_api_key", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("whatsapp_agents", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "whatsapp_agents")
    op.drop_column("system_settings", "whatsapp_api_key")
    op.drop_column("system_settings", "whatsapp_api_url")
