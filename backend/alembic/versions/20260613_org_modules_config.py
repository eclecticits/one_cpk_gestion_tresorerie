"""organisation_settings: add modules_config JSONB column

Revision ID: 20260613_org_modules
Revises: 20260613_ai_providers
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260613_org_modules"
down_revision = "20260613_ai_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column(
            "modules_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Configuration détaillée par module (RH, Secrétariat, Trésorerie…)",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisation_settings", "modules_config")
