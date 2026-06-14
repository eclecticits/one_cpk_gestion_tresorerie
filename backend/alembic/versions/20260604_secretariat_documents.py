"""add secretariat documents phase 1

Revision ID: 20260604_sec_documents
Revises: 20260604_sec_agenda
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.modules.secretariat.permissions import (
    SECRETARIAT_DOCUMENT_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260604_sec_documents"
down_revision = "20260604_sec_agenda"
branch_labels = None
depends_on = None


def _seed_permissions() -> None:
    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_DOCUMENT_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_DOCUMENT_PERMISSION_CODES)
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
        "secretariat_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("synthesis_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_secretariat_documents_organisation_id", "secretariat_documents", ["organisation_id"])
    op.create_index("ix_secretariat_documents_document_type", "secretariat_documents", ["document_type"])
    op.create_index("ix_secretariat_documents_category", "secretariat_documents", ["category"])
    op.create_index("ix_secretariat_documents_status", "secretariat_documents", ["status"])
    op.create_index("ix_secretariat_documents_created_at", "secretariat_documents", ["created_at"])
    op.create_index("ix_sec_documents_org_type_status", "secretariat_documents", ["organisation_id", "document_type", "status"])
    op.create_index("ix_sec_documents_org_cat_status", "secretariat_documents", ["organisation_id", "category", "status"])
    op.create_index("ix_sec_documents_org_created_at", "secretariat_documents", ["organisation_id", "created_at"])

    op.create_table(
        "secretariat_document_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("synthesis_text", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["secretariat_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "document_id", "version_number", name="uq_secretariat_document_version"),
    )
    op.create_index("ix_secretariat_document_versions_organisation_id", "secretariat_document_versions", ["organisation_id"])
    op.create_index("ix_secretariat_document_versions_document_id", "secretariat_document_versions", ["document_id"])
    op.create_index("ix_secretariat_document_versions_version_number", "secretariat_document_versions", ["version_number"])
    op.create_index("ix_sec_doc_versions_org_doc_ver", "secretariat_document_versions", ["organisation_id", "document_id", "version_number"])

    _seed_permissions()


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_DOCUMENT_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
    op.drop_index("ix_sec_doc_versions_org_doc_ver", table_name="secretariat_document_versions")
    op.drop_index("ix_secretariat_document_versions_version_number", table_name="secretariat_document_versions")
    op.drop_index("ix_secretariat_document_versions_document_id", table_name="secretariat_document_versions")
    op.drop_index("ix_secretariat_document_versions_organisation_id", table_name="secretariat_document_versions")
    op.drop_table("secretariat_document_versions")
    op.drop_index("ix_sec_documents_org_created_at", table_name="secretariat_documents")
    op.drop_index("ix_sec_documents_org_cat_status", table_name="secretariat_documents")
    op.drop_index("ix_sec_documents_org_type_status", table_name="secretariat_documents")
    op.drop_index("ix_secretariat_documents_created_at", table_name="secretariat_documents")
    op.drop_index("ix_secretariat_documents_status", table_name="secretariat_documents")
    op.drop_index("ix_secretariat_documents_category", table_name="secretariat_documents")
    op.drop_index("ix_secretariat_documents_document_type", table_name="secretariat_documents")
    op.drop_index("ix_secretariat_documents_organisation_id", table_name="secretariat_documents")
    op.drop_table("secretariat_documents")
