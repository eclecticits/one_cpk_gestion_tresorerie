"""add secretariat reunion agent phase 1

Revision ID: 20260604_sec_reunions
Revises: 20260604_sec_security
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_MEETING_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260604_sec_reunions"
down_revision = "20260604_sec_security"
branch_labels = None
depends_on = None


def _seed_permissions() -> None:
    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_MEETING_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MEETING_PERMISSION_CODES)
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


def upgrade() -> None:
    op.create_table(
        "secretariat_meetings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meeting_type", sa.String(length=80), nullable=False, server_default="administrative"),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("meeting_date", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("agenda_text", sa.Text(), nullable=True),
        sa.Column("invitation_draft", sa.Text(), nullable=True),
        sa.Column("minutes_draft", sa.Text(), nullable=True),
        sa.Column("approved_minutes", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_meetings_organisation_id", "secretariat_meetings", ["organisation_id"])
    op.create_index("ix_secretariat_meetings_status", "secretariat_meetings", ["status"])
    op.create_index("ix_secretariat_meetings_meeting_date", "secretariat_meetings", ["meeting_date"])

    op.create_table(
        "secretariat_meeting_participants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=120), nullable=True),
        sa.Column("attendance_status", sa.String(length=30), nullable=False, server_default="invited"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["secretariat_meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_meeting_participants_organisation_id", "secretariat_meeting_participants", ["organisation_id"])
    op.create_index("ix_secretariat_meeting_participants_meeting_id", "secretariat_meeting_participants", ["meeting_id"])

    op.create_table(
        "secretariat_meeting_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("decision_text", sa.Text(), nullable=False),
        sa.Column("responsible_name", sa.String(length=180), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["secretariat_meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_meeting_decisions_organisation_id", "secretariat_meeting_decisions", ["organisation_id"])
    op.create_index("ix_secretariat_meeting_decisions_meeting_id", "secretariat_meeting_decisions", ["meeting_id"])
    op.create_index("ix_secretariat_meeting_decisions_status", "secretariat_meeting_decisions", ["status"])
    op.create_index("ix_secretariat_meeting_decisions_org_meeting_status", "secretariat_meeting_decisions", ["organisation_id", "meeting_id", "status"])

    op.create_table(
        "secretariat_meeting_action_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("responsible_name", sa.String(length=180), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["secretariat_meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_meeting_action_items_organisation_id", "secretariat_meeting_action_items", ["organisation_id"])
    op.create_index("ix_secretariat_meeting_action_items_meeting_id", "secretariat_meeting_action_items", ["meeting_id"])
    op.create_index("ix_secretariat_meeting_action_items_status", "secretariat_meeting_action_items", ["status"])
    op.create_index("ix_secretariat_meeting_action_items_org_meeting_status", "secretariat_meeting_action_items", ["organisation_id", "meeting_id", "status"])

    _seed_permissions()


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MEETING_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
    op.drop_index("ix_secretariat_meeting_action_items_org_meeting_status", table_name="secretariat_meeting_action_items")
    op.drop_index("ix_secretariat_meeting_action_items_status", table_name="secretariat_meeting_action_items")
    op.drop_index("ix_secretariat_meeting_action_items_meeting_id", table_name="secretariat_meeting_action_items")
    op.drop_index("ix_secretariat_meeting_action_items_organisation_id", table_name="secretariat_meeting_action_items")
    op.drop_table("secretariat_meeting_action_items")
    op.drop_index("ix_secretariat_meeting_decisions_org_meeting_status", table_name="secretariat_meeting_decisions")
    op.drop_index("ix_secretariat_meeting_decisions_status", table_name="secretariat_meeting_decisions")
    op.drop_index("ix_secretariat_meeting_decisions_meeting_id", table_name="secretariat_meeting_decisions")
    op.drop_index("ix_secretariat_meeting_decisions_organisation_id", table_name="secretariat_meeting_decisions")
    op.drop_table("secretariat_meeting_decisions")
    op.drop_index("ix_secretariat_meeting_participants_meeting_id", table_name="secretariat_meeting_participants")
    op.drop_index("ix_secretariat_meeting_participants_organisation_id", table_name="secretariat_meeting_participants")
    op.drop_table("secretariat_meeting_participants")
    op.drop_index("ix_secretariat_meetings_meeting_date", table_name="secretariat_meetings")
    op.drop_index("ix_secretariat_meetings_status", table_name="secretariat_meetings")
    op.drop_index("ix_secretariat_meetings_organisation_id", table_name="secretariat_meetings")
    op.drop_table("secretariat_meetings")
