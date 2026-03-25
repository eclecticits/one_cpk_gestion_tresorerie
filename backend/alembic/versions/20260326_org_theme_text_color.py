"""Add theme text color to organisation settings.

Revision ID: 20260326_org_theme_text_color
Revises: 20260325_org_theme_settings
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_org_theme_text_color"
down_revision = "20260325_org_theme_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_text_color",
            sa.String(length=20),
            nullable=False,
            server_default="#2d3748",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisation_settings", "theme_text_color")
