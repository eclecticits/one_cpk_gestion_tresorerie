"""add system settings for notifications

Revision ID: 20260210_system_settings
Revises: 20260209_annex_multi
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260210_system_settings"
down_revision = "20260209_annex_multi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email_expediteur", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("email_president", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("emails_bureau_cc", sa.Text(), nullable=False, server_default=""),
        sa.Column("smtp_host", sa.String(length=200), nullable=False, server_default="smtp.gmail.com"),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="465"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
