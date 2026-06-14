"""Add google_oauth_redirect_uri_local to platform_settings

Revision ID: 20260614_google_oauth_local_uri
Revises: 20260614_platform_google_oauth
Create Date: 2026-06-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260614_google_oauth_local_uri"
down_revision = "20260614_platform_google_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_settings", sa.Column("google_oauth_redirect_uri_local", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_settings", "google_oauth_redirect_uri_local")
