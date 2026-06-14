"""add secretariat mail ai drafts

Revision ID: 20260603_sec_ai
Revises: 20260603_secretariat
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_MAIL_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260603_sec_ai"
down_revision = "20260603_secretariat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secretariat_mail_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("ai_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secretariat_mail_drafts_gmail_message_id"), "secretariat_mail_drafts", ["gmail_message_id"], unique=False)
    op.create_index(op.f("ix_secretariat_mail_drafts_gmail_thread_id"), "secretariat_mail_drafts", ["gmail_thread_id"], unique=False)
    op.create_index(op.f("ix_secretariat_mail_drafts_organisation_id"), "secretariat_mail_drafts", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_secretariat_mail_drafts_status"), "secretariat_mail_drafts", ["status"], unique=False)
    op.create_index(op.f("ix_secretariat_mail_drafts_user_id"), "secretariat_mail_drafts", ["user_id"], unique=False)

    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_MAIL_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MAIL_PERMISSION_CODES)
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MAIL_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")

    op.drop_index(op.f("ix_secretariat_mail_drafts_user_id"), table_name="secretariat_mail_drafts")
    op.drop_index(op.f("ix_secretariat_mail_drafts_status"), table_name="secretariat_mail_drafts")
    op.drop_index(op.f("ix_secretariat_mail_drafts_organisation_id"), table_name="secretariat_mail_drafts")
    op.drop_index(op.f("ix_secretariat_mail_drafts_gmail_thread_id"), table_name="secretariat_mail_drafts")
    op.drop_index(op.f("ix_secretariat_mail_drafts_gmail_message_id"), table_name="secretariat_mail_drafts")
    op.drop_table("secretariat_mail_drafts")
