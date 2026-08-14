"""journal de consommation IA par organisation

Revision ID: 20260814_ai_usage_log
Revises: 20260814_budget_incl_calc
Create Date: 2026-08-14 14:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260814_ai_usage_log"
down_revision = "20260814_budget_incl_calc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Pas de cle etrangere vers organisations : c'est un journal, il doit
        # survivre a toute reorganisation et ne jamais bloquer une suppression.
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("module", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_ai_usage_logs_organisation_id", "ai_usage_logs", ["organisation_id"])
    op.create_index("ix_ai_usage_logs_created_at", "ai_usage_logs", ["created_at"])
    op.create_index("ix_ai_usage_org_date", "ai_usage_logs", ["organisation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_org_date", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_created_at", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_organisation_id", table_name="ai_usage_logs")
    op.drop_table("ai_usage_logs")
