"""ai_provider_configs table

Revision ID: 20260613_ai_providers
Revises: 20260605_sec_roles
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260613_ai_providers"
down_revision = "20260605_sec_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=30), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("default_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fallback_priority", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_provider_configs_organisation_id", "ai_provider_configs", ["organisation_id"])
    op.create_index("ix_ai_provider_configs_provider_type", "ai_provider_configs", ["provider_type"])


def downgrade() -> None:
    op.drop_index("ix_ai_provider_configs_provider_type", table_name="ai_provider_configs")
    op.drop_index("ix_ai_provider_configs_organisation_id", table_name="ai_provider_configs")
    op.drop_table("ai_provider_configs")
