"""add attendance agent releases commands and revocation

Revision ID: 20260816_hr_agent_phase2
Revises: 20260816_hr_agent_enroll
Create Date: 2026-08-16 23:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_hr_agent_phase2"
down_revision = "20260816_hr_agent_enroll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_attendance_agents", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hr_attendance_agents", sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_hr_attendance_agents_revoked_by_users", "hr_attendance_agents", "users", ["revoked_by"], ["id"], ondelete="SET NULL")

    op.add_column("hr_attendance_devices", sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hr_attendance_devices", sa.Column("last_test_latency_ms", sa.Integer(), nullable=True))
    op.add_column("hr_attendance_devices", sa.Column("last_test_result_json", postgresql.JSONB(), nullable=True))

    op.create_table(
        "hr_attendance_agent_releases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("architecture", sa.String(length=30), nullable=False, server_default="x64"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("minimum_backend_version", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", "platform", "architecture", name="uq_hr_agent_release_version_platform_arch"),
    )
    op.create_index("ix_hr_agent_release_active_platform", "hr_attendance_agent_releases", ["is_active", "platform", "architecture"])

    op.create_table(
        "hr_attendance_agent_commands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("command_type", sa.String(length=50), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["hr_attendance_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["hr_attendance_devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hr_attendance_agent_commands_tenant_id", "hr_attendance_agent_commands", ["tenant_id"])
    op.create_index("ix_hr_attendance_agent_commands_agent_id", "hr_attendance_agent_commands", ["agent_id"])
    op.create_index("ix_hr_attendance_agent_commands_device_id", "hr_attendance_agent_commands", ["device_id"])
    op.create_index("ix_hr_agent_command_tenant_status", "hr_attendance_agent_commands", ["tenant_id", "status"])
    op.create_index("ix_hr_agent_command_agent_status", "hr_attendance_agent_commands", ["agent_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_hr_agent_command_agent_status", table_name="hr_attendance_agent_commands")
    op.drop_index("ix_hr_agent_command_tenant_status", table_name="hr_attendance_agent_commands")
    op.drop_index("ix_hr_attendance_agent_commands_device_id", table_name="hr_attendance_agent_commands")
    op.drop_index("ix_hr_attendance_agent_commands_agent_id", table_name="hr_attendance_agent_commands")
    op.drop_index("ix_hr_attendance_agent_commands_tenant_id", table_name="hr_attendance_agent_commands")
    op.drop_table("hr_attendance_agent_commands")
    op.drop_index("ix_hr_agent_release_active_platform", table_name="hr_attendance_agent_releases")
    op.drop_table("hr_attendance_agent_releases")
    op.drop_column("hr_attendance_devices", "last_test_result_json")
    op.drop_column("hr_attendance_devices", "last_test_latency_ms")
    op.drop_column("hr_attendance_devices", "last_test_at")
    op.drop_constraint("fk_hr_attendance_agents_revoked_by_users", "hr_attendance_agents", type_="foreignkey")
    op.drop_column("hr_attendance_agents", "revoked_by")
    op.drop_column("hr_attendance_agents", "revoked_at")
