"""Socle multi-source préparatoire du module Tableau.

Cette migration reste strictement dans le domaine Tableau. Elle ne crée aucune
référence vers le registre officiel ``experts_comptables``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260916_tableau_multisource"
down_revision = "20260915_tableau_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("secretariat_tableau_imports", sa.Column("source_type", sa.String(30), nullable=True))
    op.add_column("secretariat_tableau_imports", sa.Column("file_sha256", sa.String(64), nullable=True))
    op.add_column("secretariat_tableau_imports", sa.Column("file_size", sa.Integer(), nullable=True))
    op.add_column("secretariat_tableau_imports", sa.Column("accepted_rows", sa.Integer(), nullable=True))
    op.add_column("secretariat_tableau_imports", sa.Column("rejected_rows", sa.Integer(), nullable=True))
    op.add_column("secretariat_tableau_imports", sa.Column("error_count", sa.Integer(), nullable=True))

    op.execute("UPDATE secretariat_tableau_imports SET source_type = 'tableau' WHERE source_type IS NULL")
    op.execute("UPDATE secretariat_tableau_imports SET accepted_rows = imported_rows WHERE accepted_rows IS NULL")
    op.execute("UPDATE secretariat_tableau_imports SET rejected_rows = 0 WHERE rejected_rows IS NULL")
    op.execute("UPDATE secretariat_tableau_imports SET error_count = 0 WHERE error_count IS NULL")

    op.alter_column("secretariat_tableau_imports", "source_type", existing_type=sa.String(30), nullable=False, server_default="tableau")
    op.alter_column("secretariat_tableau_imports", "accepted_rows", existing_type=sa.Integer(), nullable=False, server_default="0")
    op.alter_column("secretariat_tableau_imports", "rejected_rows", existing_type=sa.Integer(), nullable=False, server_default="0")
    op.alter_column("secretariat_tableau_imports", "error_count", existing_type=sa.Integer(), nullable=False, server_default="0")
    op.create_check_constraint(
        "ck_tableau_import_source_type",
        "secretariat_tableau_imports",
        "source_type IN ('personnes_physiques', 'personnes_morales', 'chiffres_affaires', 'assurances', 'tableau')",
    )
    op.create_index("ix_tableau_imports_source_type", "secretariat_tableau_imports", ["source_type"])
    op.create_index("ix_tableau_imports_file_sha256", "secretariat_tableau_imports", ["file_sha256"])

    op.create_table(
        "tableau_source_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.Column("normalization_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("normalization_errors", postgresql.JSONB(), nullable=True),
        sa.Column("business_key_candidate", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("import_id", "line_number", name="uq_tableau_source_row_line"),
    )
    op.create_index("ix_tableau_source_rows_organisation_id", "tableau_source_rows", ["organisation_id"])
    op.create_index("ix_tableau_source_rows_import_id", "tableau_source_rows", ["import_id"])
    op.create_index("ix_tableau_source_rows_row_hash", "tableau_source_rows", ["row_hash"])
    op.create_index("ix_tableau_source_rows_normalization_status", "tableau_source_rows", ["normalization_status"])
    op.create_index("ix_tableau_source_rows_business_key", "tableau_source_rows", ["business_key_candidate"])


def downgrade() -> None:
    op.drop_index("ix_tableau_source_rows_business_key", table_name="tableau_source_rows")
    op.drop_index("ix_tableau_source_rows_normalization_status", table_name="tableau_source_rows")
    op.drop_index("ix_tableau_source_rows_row_hash", table_name="tableau_source_rows")
    op.drop_index("ix_tableau_source_rows_import_id", table_name="tableau_source_rows")
    op.drop_index("ix_tableau_source_rows_organisation_id", table_name="tableau_source_rows")
    op.drop_table("tableau_source_rows")
    op.drop_constraint("ck_tableau_import_source_type", "secretariat_tableau_imports", type_="check")
    op.drop_index("ix_tableau_imports_file_sha256", table_name="secretariat_tableau_imports")
    op.drop_index("ix_tableau_imports_source_type", table_name="secretariat_tableau_imports")
    op.drop_column("secretariat_tableau_imports", "error_count")
    op.drop_column("secretariat_tableau_imports", "rejected_rows")
    op.drop_column("secretariat_tableau_imports", "accepted_rows")
    op.drop_column("secretariat_tableau_imports", "file_size")
    op.drop_column("secretariat_tableau_imports", "file_sha256")
    op.drop_column("secretariat_tableau_imports", "source_type")
