"""add attendance agent enrollments

Revision ID: 20260816_hr_agent_enroll
Revises: 20260816_hr_agents
Create Date: 2026-08-16 22:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_hr_agent_enroll"
down_revision = "20260816_hr_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_attendance_agent_enrollments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("api_base_url", sa.String(length=255), nullable=False),
        sa.Column("device_code", sa.String(length=100), nullable=False),
        sa.Column("device_name", sa.String(length=150), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="hikvision"),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("local_host", sa.String(length=100), nullable=False),
        sa.Column("local_port", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["hr_attendance_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_hr_agent_enrollment_token_hash"),
    )
    op.create_index("ix_hr_attendance_agent_enrollments_tenant_id", "hr_attendance_agent_enrollments", ["tenant_id"])
    op.create_index("ix_hr_attendance_agent_enrollments_agent_id", "hr_attendance_agent_enrollments", ["agent_id"])
    op.create_index("ix_hr_agent_enrollment_tenant_status", "hr_attendance_agent_enrollments", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_hr_agent_enrollment_tenant_status", table_name="hr_attendance_agent_enrollments")
    op.drop_index("ix_hr_attendance_agent_enrollments_agent_id", table_name="hr_attendance_agent_enrollments")
    op.drop_index("ix_hr_attendance_agent_enrollments_tenant_id", table_name="hr_attendance_agent_enrollments")
    op.drop_table("hr_attendance_agent_enrollments")
