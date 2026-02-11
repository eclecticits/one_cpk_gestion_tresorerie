"""add sortie pdf and notification settings

Revision ID: 20260211_sortie_notifications
Revises: 20260210_smtp_password
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211_sortie_notifications"
down_revision = "20260210_smtp_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("email_tresorier", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("emails_bureau_sortie_cc", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("sorties_fonds", sa.Column("pdf_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("sorties_fonds", "pdf_path")
    op.drop_column("system_settings", "emails_bureau_sortie_cc")
    op.drop_column("system_settings", "email_tresorier")
