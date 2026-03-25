"""Add theme colors to organisation settings.

Revision ID: 20260325_org_theme_settings
Revises: 20260325_seed_core_budget_postes
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_org_theme_settings"
down_revision = "20260325_seed_core_budget_postes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_primary_color",
            sa.String(length=20),
            nullable=False,
            server_default="#4a9079",
        ),
    )
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_sidebar_color",
            sa.String(length=20),
            nullable=False,
            server_default="#3d7a66",
        ),
    )
    op.add_column(
        "organisation_settings",
        sa.Column(
            "theme_accent_color",
            sa.String(length=20),
            nullable=False,
            server_default="#eab308",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisation_settings", "theme_accent_color")
    op.drop_column("organisation_settings", "theme_sidebar_color")
    op.drop_column("organisation_settings", "theme_primary_color")
