"""add secretariat agenda phase 1

Revision ID: 20260604_sec_agenda
Revises: 20260604_reunion_idx_lock
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_AGENDA_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260604_sec_agenda"
down_revision = "20260604_reunion_idx_lock"
branch_labels = None
depends_on = None


def _seed_permissions() -> None:
    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_AGENDA_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_AGENDA_PERMISSION_CODES)
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
        "secretariat_agenda_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("item_type", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_agenda_items_organisation_id", "secretariat_agenda_items", ["organisation_id"])
    op.create_index("ix_secretariat_agenda_items_status", "secretariat_agenda_items", ["status"])
    op.create_index("ix_secretariat_agenda_items_due_at", "secretariat_agenda_items", ["due_at"])
    op.create_index("ix_sec_agenda_items_org_status_due", "secretariat_agenda_items", ["organisation_id", "status", "due_at"])
    op.create_index("ix_sec_agenda_items_org_assignee_status", "secretariat_agenda_items", ["organisation_id", "assigned_to_user_id", "status"])
    op.create_index("ix_sec_agenda_items_org_type_target", "secretariat_agenda_items", ["organisation_id", "item_type", "target_type", "target_id"])

    op.create_table(
        "secretariat_agenda_reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("agenda_item_id", sa.Integer(), nullable=False),
        sa.Column("reminder_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["agenda_item_id"], ["secretariat_agenda_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_agenda_reminders_organisation_id", "secretariat_agenda_reminders", ["organisation_id"])
    op.create_index("ix_secretariat_agenda_reminders_agenda_item_id", "secretariat_agenda_reminders", ["agenda_item_id"])
    op.create_index("ix_secretariat_agenda_reminders_reminder_at", "secretariat_agenda_reminders", ["reminder_at"])
    op.create_index("ix_secretariat_agenda_reminders_status", "secretariat_agenda_reminders", ["status"])
    op.create_index("ix_sec_agenda_rem_org_at_status", "secretariat_agenda_reminders", ["organisation_id", "reminder_at", "status"])
    op.create_index("ix_sec_agenda_rem_org_item", "secretariat_agenda_reminders", ["organisation_id", "agenda_item_id"])

    _seed_permissions()


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_AGENDA_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
    op.drop_index("ix_sec_agenda_rem_org_item", table_name="secretariat_agenda_reminders")
    op.drop_index("ix_sec_agenda_rem_org_at_status", table_name="secretariat_agenda_reminders")
    op.drop_index("ix_secretariat_agenda_reminders_status", table_name="secretariat_agenda_reminders")
    op.drop_index("ix_secretariat_agenda_reminders_reminder_at", table_name="secretariat_agenda_reminders")
    op.drop_index("ix_secretariat_agenda_reminders_agenda_item_id", table_name="secretariat_agenda_reminders")
    op.drop_index("ix_secretariat_agenda_reminders_organisation_id", table_name="secretariat_agenda_reminders")
    op.drop_table("secretariat_agenda_reminders")
    op.drop_index("ix_sec_agenda_items_org_type_target", table_name="secretariat_agenda_items")
    op.drop_index("ix_sec_agenda_items_org_assignee_status", table_name="secretariat_agenda_items")
    op.drop_index("ix_sec_agenda_items_org_status_due", table_name="secretariat_agenda_items")
    op.drop_index("ix_secretariat_agenda_items_due_at", table_name="secretariat_agenda_items")
    op.drop_index("ix_secretariat_agenda_items_status", table_name="secretariat_agenda_items")
    op.drop_index("ix_secretariat_agenda_items_organisation_id", table_name="secretariat_agenda_items")
    op.drop_table("secretariat_agenda_items")
