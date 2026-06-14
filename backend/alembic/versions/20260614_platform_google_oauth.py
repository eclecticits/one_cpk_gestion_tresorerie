"""Add Google OAuth columns to platform_settings

Revision ID: 20260614_platform_google_oauth
Revises: f1b0b5ff77bb
Create Date: 2026-06-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260614_platform_google_oauth"
down_revision = "20260614_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_settings", sa.Column("google_client_id", sa.String(300), nullable=True))
    op.add_column("platform_settings", sa.Column("google_client_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("platform_settings", sa.Column("google_oauth_redirect_uri", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_settings", "google_oauth_redirect_uri")
    op.drop_column("platform_settings", "google_client_secret_encrypted")
    op.drop_column("platform_settings", "google_client_id")
