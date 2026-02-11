"""add workflow notification settings

Revision ID: 20260211_workflow_settings
Revises: 20260211_rbac_roles_permissions
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211_workflow_settings"
down_revision = "20260211_rbac_roles_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("email_validation_1", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("email_validation_final", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("max_caisse_amount", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "max_caisse_amount")
    op.drop_column("system_settings", "email_validation_final")
    op.drop_column("system_settings", "email_validation_1")
