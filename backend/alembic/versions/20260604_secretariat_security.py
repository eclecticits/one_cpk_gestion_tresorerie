"""harden secretariat workflow indexes

Revision ID: 20260604_sec_security
Revises: 20260603_approvals
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260604_sec_security"
down_revision = "20260603_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_oauth_connections_active_org_user_provider",
        "oauth_connections",
        ["organisation_id", "user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("status = 'connected'"),
    )
    op.create_index(
        "ix_secretariat_approvals_org_status_created",
        "secretariat_approvals",
        ["organisation_id", "status", "created_at"],
    )
    op.create_index(
        "ix_secretariat_approvals_org_type_target_status",
        "secretariat_approvals",
        ["organisation_id", "approval_type", "target_type", "target_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_secretariat_approvals_org_type_target_status", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_org_status_created", table_name="secretariat_approvals")
    op.drop_index("uq_oauth_connections_active_org_user_provider", table_name="oauth_connections")
