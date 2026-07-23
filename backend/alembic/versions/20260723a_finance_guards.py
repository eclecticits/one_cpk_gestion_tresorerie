"""Garde-fous financiers : unicité de la caisse par tenant.

Revision ID: 20260723a_finance_guards
Revises: 20260722d_perf_indexes
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723a_finance_guards"
down_revision = "20260722d_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH keepers AS (
            SELECT
                organisation_id,
                MIN(id) AS keep_id,
                COALESCE(SUM(solde_usd), 0) AS total_usd,
                COALESCE(SUM(solde_cdf), 0) AS total_cdf,
                BOOL_OR(est_ouverte) AS any_open,
                MAX(derniere_maj) AS last_update
            FROM caisse_centrale
            GROUP BY organisation_id
        )
        UPDATE caisse_centrale c
        SET
            solde_usd = k.total_usd,
            solde_cdf = k.total_cdf,
            est_ouverte = k.any_open,
            derniere_maj = k.last_update
        FROM keepers k
        WHERE c.id = k.keep_id
        """
    )
    op.execute(
        """
        DELETE FROM caisse_centrale c
        USING caisse_centrale kept
        WHERE c.organisation_id = kept.organisation_id
          AND c.id > kept.id
        """
    )
    op.create_unique_constraint(
        "uq_caisse_centrale_organisation_id",
        "caisse_centrale",
        ["organisation_id"],
    )
    op.execute(
        """
        ALTER TABLE caisse_centrale
        ADD CONSTRAINT ck_caisse_centrale_solde_usd_nonnegative
        CHECK (solde_usd >= 0) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE caisse_centrale
        ADD CONSTRAINT ck_caisse_centrale_solde_cdf_nonnegative
        CHECK (solde_cdf >= 0) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE comptes_bancaires
        ADD CONSTRAINT ck_comptes_bancaires_solde_initial_nonnegative
        CHECK (solde_initial >= 0) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE comptes_bancaires
        ADD CONSTRAINT ck_comptes_bancaires_solde_actuel_nonnegative
        CHECK (solde_actuel >= 0) NOT VALID
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY doc_type, year, tenant_id
                    ORDER BY counter DESC, updated_at DESC, id
                ) AS rn
            FROM document_sequences
            WHERE service_id IS NULL
        )
        DELETE FROM document_sequences ds
        USING ranked r
        WHERE ds.id = r.id
          AND r.rn > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY doc_type, year, tenant_id, service_id
                    ORDER BY counter DESC, updated_at DESC, id
                ) AS rn
            FROM document_sequences
            WHERE service_id IS NOT NULL
        )
        DELETE FROM document_sequences ds
        USING ranked r
        WHERE ds.id = r.id
          AND r.rn > 1
        """
    )
    op.execute("ALTER TABLE document_sequences DROP CONSTRAINT IF EXISTS uq_doc_type_year_tenant_service")
    op.create_index(
        "uq_docseq_central",
        "document_sequences",
        ["doc_type", "year", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NULL"),
    )
    op.create_index(
        "uq_docseq_service",
        "document_sequences",
        ["doc_type", "year", "tenant_id", "service_id"],
        unique=True,
        postgresql_where=sa.text("service_id IS NOT NULL"),
    )

    op.create_index(
        "uq_budget_postes_org_exercice_code_active",
        "budget_postes",
        ["organisation_id", "exercice_id", "code"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_budget_postes_org_exercice_code_active", table_name="budget_postes")
    op.drop_index("uq_docseq_service", table_name="document_sequences")
    op.drop_index("uq_docseq_central", table_name="document_sequences")
    op.create_unique_constraint(
        "uq_doc_type_year_tenant_service",
        "document_sequences",
        ["doc_type", "year", "tenant_id", "service_id"],
    )
    op.drop_constraint(
        "ck_comptes_bancaires_solde_actuel_nonnegative",
        "comptes_bancaires",
        type_="check",
    )
    op.drop_constraint(
        "ck_comptes_bancaires_solde_initial_nonnegative",
        "comptes_bancaires",
        type_="check",
    )
    op.drop_constraint(
        "ck_caisse_centrale_solde_cdf_nonnegative",
        "caisse_centrale",
        type_="check",
    )
    op.drop_constraint(
        "ck_caisse_centrale_solde_usd_nonnegative",
        "caisse_centrale",
        type_="check",
    )
    op.drop_constraint(
        "uq_caisse_centrale_organisation_id",
        "caisse_centrale",
        type_="unique",
    )
