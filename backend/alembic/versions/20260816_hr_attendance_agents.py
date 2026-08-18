"""add attendance agents and device mappings

Revision ID: 20260816_hr_agents
Revises: 20260816_hr_punches
Create Date: 2026-08-16 20:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_hr_agents"
down_revision = "20260816_hr_punches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_attendance_agents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("hostname", sa.String(length=150), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "agent_id", name="uq_hr_attendance_agents_tenant_agent"),
    )
    op.create_index("ix_hr_attendance_agents_tenant_id", "hr_attendance_agents", ["tenant_id"])

    op.create_table(
        "hr_attendance_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("local_host", sa.String(length=100), nullable=True),
        sa.Column("local_port", sa.Integer(), nullable=True),
        sa.Column("serial_number", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("firmware", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="UNKNOWN"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("today_punch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["hr_attendance_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_hr_attendance_devices_tenant_code"),
    )
    op.create_index("ix_hr_attendance_devices_tenant_id", "hr_attendance_devices", ["tenant_id"])
    op.create_index("ix_hr_attendance_devices_agent_id", "hr_attendance_devices", ["agent_id"])

    op.create_table(
        "hr_attendance_device_employee_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("external_employee_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["hr_attendance_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_id", "external_employee_id", name="uq_hr_attendance_mapping_device_external_employee"),
    )
    op.create_index("ix_hr_attendance_device_employee_mappings_tenant_id", "hr_attendance_device_employee_mappings", ["tenant_id"])
    op.create_index("ix_hr_attendance_device_employee_mappings_device_id", "hr_attendance_device_employee_mappings", ["device_id"])
    op.create_index("ix_hr_attendance_device_employee_mappings_employee_id", "hr_attendance_device_employee_mappings", ["employee_id"])

    op.create_table(
        "hr_attendance_unmapped_punches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("external_employee_id", sa.String(length=100), nullable=False),
        sa.Column("punched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="DEVICE"),
        sa.Column("external_reference", sa.String(length=150), nullable=False),
        sa.Column("raw_event_type", sa.String(length=100), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="UNMAPPED_EMPLOYEE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["hr_attendance_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_id", "external_reference", name="uq_hr_unmapped_punch_device_external_ref"),
    )
    op.create_index("ix_hr_attendance_unmapped_punches_tenant_id", "hr_attendance_unmapped_punches", ["tenant_id"])
    op.create_index("ix_hr_attendance_unmapped_punches_device_id", "hr_attendance_unmapped_punches", ["device_id"])
    op.create_index("ix_hr_attendance_unmapped_punches_punched_at", "hr_attendance_unmapped_punches", ["punched_at"])
    op.create_index("ix_hr_unmapped_punch_tenant_status", "hr_attendance_unmapped_punches", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_hr_unmapped_punch_tenant_status", table_name="hr_attendance_unmapped_punches")
    op.drop_index("ix_hr_attendance_unmapped_punches_punched_at", table_name="hr_attendance_unmapped_punches")
    op.drop_index("ix_hr_attendance_unmapped_punches_device_id", table_name="hr_attendance_unmapped_punches")
    op.drop_index("ix_hr_attendance_unmapped_punches_tenant_id", table_name="hr_attendance_unmapped_punches")
    op.drop_table("hr_attendance_unmapped_punches")
    op.drop_index("ix_hr_attendance_device_employee_mappings_employee_id", table_name="hr_attendance_device_employee_mappings")
    op.drop_index("ix_hr_attendance_device_employee_mappings_device_id", table_name="hr_attendance_device_employee_mappings")
    op.drop_index("ix_hr_attendance_device_employee_mappings_tenant_id", table_name="hr_attendance_device_employee_mappings")
    op.drop_table("hr_attendance_device_employee_mappings")
    op.drop_index("ix_hr_attendance_devices_agent_id", table_name="hr_attendance_devices")
    op.drop_index("ix_hr_attendance_devices_tenant_id", table_name="hr_attendance_devices")
    op.drop_table("hr_attendance_devices")
    op.drop_index("ix_hr_attendance_agents_tenant_id", table_name="hr_attendance_agents")
    op.drop_table("hr_attendance_agents")
