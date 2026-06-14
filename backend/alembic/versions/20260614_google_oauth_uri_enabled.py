"""Add enabled toggles for Google OAuth redirect URIs

Revision ID: goauth_uri_enabled
Revises: 20260614_google_oauth_local_uri
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "goauth_uri_enabled"
down_revision = "20260614_google_oauth_local_uri"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_settings",
        sa.Column("google_oauth_redirect_uri_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "platform_settings",
        sa.Column("google_oauth_redirect_uri_local_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("platform_settings", "google_oauth_redirect_uri_local_enabled")
    op.drop_column("platform_settings", "google_oauth_redirect_uri_enabled")
