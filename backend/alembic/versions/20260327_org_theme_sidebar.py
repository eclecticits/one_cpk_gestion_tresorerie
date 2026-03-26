"""Add sidebar and button theme colors to organisation settings.

Revision ID: 20260327_org_theme_sidebar
Revises: 20260326_merge_org_theme_svc
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260327_org_theme_sidebar"
down_revision = "20260326_merge_org_theme_svc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_sidebar_text_color",
            sa.String(length=20),
            nullable=False,
            server_default="#ffffff",
        ),
    )
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_sidebar_active_color",
            sa.String(length=20),
            nullable=False,
            server_default="#1a523f",
        ),
    )
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_button_text_color",
            sa.String(length=20),
            nullable=False,
            server_default="#ffffff",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisation_settings", "theme_button_text_color")
    op.drop_column("organisation_settings", "theme_sidebar_active_color")
    op.drop_column("organisation_settings", "theme_sidebar_text_color")
