"""add secretariat approvals

Revision ID: 20260603_approvals
Revises: 20260603_mgr_perm
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_APPROVAL_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260603_approvals"
down_revision = "20260603_mgr_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secretariat_approvals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_type", sa.String(length=30), nullable=False),
        sa.Column("approval_type", sa.String(length=60), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_approvals_organisation_id", "secretariat_approvals", ["organisation_id"])
    op.create_index("ix_secretariat_approvals_requested_by_user_id", "secretariat_approvals", ["requested_by_user_id"])
    op.create_index("ix_secretariat_approvals_approved_by_user_id", "secretariat_approvals", ["approved_by_user_id"])
    op.create_index("ix_secretariat_approvals_agent_type", "secretariat_approvals", ["agent_type"])
    op.create_index("ix_secretariat_approvals_approval_type", "secretariat_approvals", ["approval_type"])
    op.create_index("ix_secretariat_approvals_target_type", "secretariat_approvals", ["target_type"])
    op.create_index("ix_secretariat_approvals_target_id", "secretariat_approvals", ["target_id"])
    op.create_index("ix_secretariat_approvals_status", "secretariat_approvals", ["status"])
    op.create_index("ix_secretariat_approvals_priority", "secretariat_approvals", ["priority"])

    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_APPROVAL_PERMISSION_CODES
    )
    op.execute(
        f"""
        INSERT INTO permissions (code, description, created_at)
        VALUES
        {values}
        ON CONFLICT (code) DO UPDATE
        SET description = EXCLUDED.description;
        """
    )
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_APPROVAL_PERMISSION_CODES)
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ({codes})
        WHERE r.code = 'admin'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_APPROVAL_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
    op.drop_index("ix_secretariat_approvals_priority", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_status", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_target_id", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_target_type", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_approval_type", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_agent_type", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_approved_by_user_id", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_requested_by_user_id", table_name="secretariat_approvals")
    op.drop_index("ix_secretariat_approvals_organisation_id", table_name="secretariat_approvals")
    op.drop_table("secretariat_approvals")
