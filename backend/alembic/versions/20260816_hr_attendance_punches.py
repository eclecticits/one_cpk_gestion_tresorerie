"""add raw HR attendance punches

Revision ID: 20260816_hr_punches
Revises: 20260816_paiement_mixte
Create Date: 2026-08-16 18:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_hr_punches"
down_revision = "20260816_paiement_mixte"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES
            ('rh.attendance.export', 'RH - exporter les présences', NOW()),
            ('rh.attendance.correct', 'RH - corriger les pointages', NOW())
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.add_column(
        "hr_attendances",
        sa.Column("source", sa.String(length=30), nullable=False, server_default="MANUAL"),
    )
    op.add_column(
        "hr_attendances",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "hr_attendance_punches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("punched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="MANUAL"),
        sa.Column("device_id", sa.String(length=100), nullable=True),
        sa.Column("external_reference", sa.String(length=150), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_id", "external_reference", name="uq_hr_punch_tenant_device_external_ref"),
    )
    op.create_index("ix_hr_attendance_punches_tenant_id", "hr_attendance_punches", ["tenant_id"])
    op.create_index("ix_hr_attendance_punches_employee_id", "hr_attendance_punches", ["employee_id"])
    op.create_index("ix_hr_attendance_punches_punched_at", "hr_attendance_punches", ["punched_at"])
    op.create_index("ix_hr_punch_tenant_employee_time", "hr_attendance_punches", ["tenant_id", "employee_id", "punched_at"])
    op.create_index("ix_hr_punch_tenant_time", "hr_attendance_punches", ["tenant_id", "punched_at"])
    op.create_index("ix_hr_punch_tenant_source", "hr_attendance_punches", ["tenant_id", "source"])

    op.alter_column("hr_attendances", "source", server_default=None)
    op.alter_column("hr_attendances", "updated_at", server_default=None)
    op.alter_column("hr_attendance_punches", "source", server_default=None)
    op.alter_column("hr_attendance_punches", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_hr_punch_tenant_source", table_name="hr_attendance_punches")
    op.drop_index("ix_hr_punch_tenant_time", table_name="hr_attendance_punches")
    op.drop_index("ix_hr_punch_tenant_employee_time", table_name="hr_attendance_punches")
    op.drop_index("ix_hr_attendance_punches_punched_at", table_name="hr_attendance_punches")
    op.drop_index("ix_hr_attendance_punches_employee_id", table_name="hr_attendance_punches")
    op.drop_index("ix_hr_attendance_punches_tenant_id", table_name="hr_attendance_punches")
    op.drop_table("hr_attendance_punches")
    op.drop_column("hr_attendances", "updated_at")
    op.drop_column("hr_attendances", "source")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions
            WHERE code IN ('rh.attendance.export', 'rh.attendance.correct')
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE code IN ('rh.attendance.export', 'rh.attendance.correct')")
