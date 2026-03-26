"""Add tenant_id to document sequences.

Revision ID: 20260327_docseq_tenant
Revises: 20260327_org_theme_sidebar
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260327_docseq_tenant"
down_revision = "20260327_org_theme_sidebar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_sequences", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_document_sequences_tenant_id",
        "document_sequences",
        ["tenant_id"],
        unique=False,
    )
    op.execute("UPDATE document_sequences SET tenant_id = 1 WHERE tenant_id IS NULL")
    op.alter_column("document_sequences", "tenant_id", nullable=False)
    op.drop_constraint("uq_doc_type_year", "document_sequences", type_="unique")
    op.create_unique_constraint(
        "uq_doc_type_year_tenant",
        "document_sequences",
        ["doc_type", "year", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_document_sequences_tenant_id",
        "document_sequences",
        "organisations",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_document_sequences_tenant_id", "document_sequences", type_="foreignkey")
    op.drop_constraint("uq_doc_type_year_tenant", "document_sequences", type_="unique")
    op.create_unique_constraint("uq_doc_type_year", "document_sequences", ["doc_type", "year"])
    op.drop_index("ix_document_sequences_tenant_id", table_name="document_sequences")
    op.drop_column("document_sequences", "tenant_id")
