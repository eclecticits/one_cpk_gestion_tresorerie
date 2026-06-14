"""add gmail draft creation tracking

Revision ID: 20260603_gdraft
Revises: 20260603_sec_ai
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from app.modules.secretariat.permissions import (
    SECRETARIAT_MAIL_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260603_gdraft"
down_revision = "20260603_sec_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("secretariat_mail_drafts", sa.Column("source_gmail_message_id", sa.String(length=255), nullable=True))
    op.add_column("secretariat_mail_drafts", sa.Column("recipient_email", sa.String(length=320), nullable=True))
    op.add_column("secretariat_mail_drafts", sa.Column("gmail_draft_id", sa.String(length=255), nullable=True))
    op.add_column("secretariat_mail_drafts", sa.Column("gmail_draft_created_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_secretariat_mail_drafts_source_gmail_message_id"), "secretariat_mail_drafts", ["source_gmail_message_id"], unique=False)
    op.create_index(op.f("ix_secretariat_mail_drafts_gmail_draft_id"), "secretariat_mail_drafts", ["gmail_draft_id"], unique=False)

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

    op.drop_index(op.f("ix_secretariat_mail_drafts_gmail_draft_id"), table_name="secretariat_mail_drafts")
    op.drop_index(op.f("ix_secretariat_mail_drafts_source_gmail_message_id"), table_name="secretariat_mail_drafts")
    op.drop_column("secretariat_mail_drafts", "gmail_draft_created_at")
    op.drop_column("secretariat_mail_drafts", "gmail_draft_id")
    op.drop_column("secretariat_mail_drafts", "recipient_email")
    op.drop_column("secretariat_mail_drafts", "source_gmail_message_id")
