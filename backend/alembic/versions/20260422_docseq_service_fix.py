"""ensure document sequence service scope

Revision ID: 20260422_docseq_service_fix
Revises: d0af58829e2f
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op


revision = "20260422_docseq_service_fix"
down_revision = "d0af58829e2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_sequences
        ADD COLUMN IF NOT EXISTS service_id INTEGER;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_document_sequences_service_id'
            ) THEN
                ALTER TABLE document_sequences
                ADD CONSTRAINT fk_document_sequences_service_id
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_sequences_service_id
        ON document_sequences(service_id);
        """
    )
    op.execute(
        """
        ALTER TABLE document_sequences
        DROP CONSTRAINT IF EXISTS uq_doc_type_year_tenant;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_doc_type_year_tenant_service'
            ) THEN
                ALTER TABLE document_sequences
                ADD CONSTRAINT uq_doc_type_year_tenant_service
                UNIQUE (doc_type, year, tenant_id, service_id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_sequences DROP CONSTRAINT IF EXISTS uq_doc_type_year_tenant_service;")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_doc_type_year_tenant'
            ) THEN
                ALTER TABLE document_sequences
                ADD CONSTRAINT uq_doc_type_year_tenant
                UNIQUE (doc_type, year, tenant_id);
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_document_sequences_service_id;")
    op.execute("ALTER TABLE document_sequences DROP CONSTRAINT IF EXISTS fk_document_sequences_service_id;")
    op.execute("ALTER TABLE document_sequences DROP COLUMN IF EXISTS service_id;")
