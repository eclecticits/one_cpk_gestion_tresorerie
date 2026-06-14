"""add secretariat module

Revision ID: 20260603_secretariat
Revises: 20260528_hr_refs
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_CORE_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260603_secretariat"
down_revision = "20260528_hr_refs"
branch_labels = None
depends_on = None


def _seed_permissions() -> None:
    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_CORE_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_CORE_PERMISSION_CODES)
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
        "secretariat_agents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="inactive"),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_agents_organisation_id"), "secretariat_agents", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_agents_status"), "secretariat_agents", ["status"], unique=False)
    op.create_index(op.f("ix_secretariat_agents_type"), "secretariat_agents", ["type"], unique=False)

    op.create_table(
        "secretariat_conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["agent_id"], ["secretariat_agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_conversations_agent_id"), "secretariat_conversations", ["agent_id"], unique=False)
    op.create_index(op.f("ix_secretariat_conversations_organisation_id"), "secretariat_conversations", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_conversations_status"), "secretariat_conversations", ["status"], unique=False)
    op.create_index(op.f("ix_secretariat_conversations_user_id"), "secretariat_conversations", ["user_id"], unique=False)

    op.create_table(
        "secretariat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["conversation_id"], ["secretariat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_messages_conversation_id"), "secretariat_messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_messages_organisation_id"), "secretariat_messages", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_messages_sender_type"), "secretariat_messages", ["sender_type"], unique=False)

    op.create_table(
        "secretariat_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["agent_id"], ["secretariat_agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_tasks_agent_id"), "secretariat_tasks", ["agent_id"], unique=False)
    op.create_index(op.f("ix_secretariat_tasks_organisation_id"), "secretariat_tasks", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_tasks_priority"), "secretariat_tasks", ["priority"], unique=False)
    op.create_index(op.f("ix_secretariat_tasks_status"), "secretariat_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_secretariat_tasks_user_id"), "secretariat_tasks", ["user_id"], unique=False)

    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="not_configured"),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_oauth_connections_organisation_id"), "oauth_connections", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_oauth_connections_provider"), "oauth_connections", ["provider"], unique=False)
    op.create_index(op.f("ix_oauth_connections_status"), "oauth_connections", ["status"], unique=False)
    op.create_index(op.f("ix_oauth_connections_user_id"), "oauth_connections", ["user_id"], unique=False)

    op.create_table(
        "secretariat_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_type", sa.String(length=30), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=60), nullable=True),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="success"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_audit_logs_action"), "secretariat_audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_secretariat_audit_logs_agent_type"), "secretariat_audit_logs", ["agent_type"], unique=False)
    op.create_index(op.f("ix_secretariat_audit_logs_organisation_id"), "secretariat_audit_logs", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_audit_logs_status"), "secretariat_audit_logs", ["status"], unique=False)
    op.create_index(op.f("ix_secretariat_audit_logs_user_id"), "secretariat_audit_logs", ["user_id"], unique=False)

    _seed_permissions()


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_CORE_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")

    op.drop_index(op.f("ix_secretariat_audit_logs_user_id"), table_name="secretariat_audit_logs")
    op.drop_index(op.f("ix_secretariat_audit_logs_status"), table_name="secretariat_audit_logs")
    op.drop_index(op.f("ix_secretariat_audit_logs_organisation_id"), table_name="secretariat_audit_logs")
    op.drop_index(op.f("ix_secretariat_audit_logs_agent_type"), table_name="secretariat_audit_logs")
    op.drop_index(op.f("ix_secretariat_audit_logs_action"), table_name="secretariat_audit_logs")
    op.drop_table("secretariat_audit_logs")

    op.drop_index(op.f("ix_oauth_connections_user_id"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_status"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_provider"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_organisation_id"), table_name="oauth_connections")
    op.drop_table("oauth_connections")

    op.drop_index(op.f("ix_secretariat_tasks_user_id"), table_name="secretariat_tasks")
    op.drop_index(op.f("ix_secretariat_tasks_status"), table_name="secretariat_tasks")
    op.drop_index(op.f("ix_secretariat_tasks_priority"), table_name="secretariat_tasks")
    op.drop_index(op.f("ix_secretariat_tasks_organisation_id"), table_name="secretariat_tasks")
    op.drop_index(op.f("ix_secretariat_tasks_agent_id"), table_name="secretariat_tasks")
    op.drop_table("secretariat_tasks")

    op.drop_index(op.f("ix_secretariat_messages_sender_type"), table_name="secretariat_messages")
    op.drop_index(op.f("ix_secretariat_messages_organisation_id"), table_name="secretariat_messages")
    op.drop_index(op.f("ix_secretariat_messages_conversation_id"), table_name="secretariat_messages")
    op.drop_table("secretariat_messages")

    op.drop_index(op.f("ix_secretariat_conversations_user_id"), table_name="secretariat_conversations")
    op.drop_index(op.f("ix_secretariat_conversations_status"), table_name="secretariat_conversations")
    op.drop_index(op.f("ix_secretariat_conversations_organisation_id"), table_name="secretariat_conversations")
    op.drop_index(op.f("ix_secretariat_conversations_agent_id"), table_name="secretariat_conversations")
    op.drop_table("secretariat_conversations")

    op.drop_index(op.f("ix_secretariat_agents_type"), table_name="secretariat_agents")
    op.drop_index(op.f("ix_secretariat_agents_status"), table_name="secretariat_agents")
    op.drop_index(op.f("ix_secretariat_agents_organisation_id"), table_name="secretariat_agents")
    op.drop_table("secretariat_agents")
