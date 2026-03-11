"""add reconciliation fields to encaissements and sorties_fonds

Revision ID: 20260311_reconciliation_fields
Revises: 20260311_cash_accounts
Create Date: 2026-03-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260311_reconciliation_fields"
down_revision = "20260311_cash_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissements",
        sa.Column("is_reconciled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "encaissements",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "encaissements",
        sa.Column("reconciled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "encaissements",
        sa.Column("bank_statement_ref", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_encaissements_is_reconciled", "encaissements", ["is_reconciled"])

    op.add_column(
        "sorties_fonds",
        sa.Column("is_reconciled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column("reconciled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column("bank_statement_ref", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_sorties_fonds_is_reconciled", "sorties_fonds", ["is_reconciled"])

    op.alter_column("encaissements", "is_reconciled", server_default=None)
    op.alter_column("sorties_fonds", "is_reconciled", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_is_reconciled", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "bank_statement_ref")
    op.drop_column("sorties_fonds", "reconciled_by_id")
    op.drop_column("sorties_fonds", "reconciled_at")
    op.drop_column("sorties_fonds", "is_reconciled")

    op.drop_index("ix_encaissements_is_reconciled", table_name="encaissements")
    op.drop_column("encaissements", "bank_statement_ref")
    op.drop_column("encaissements", "reconciled_by_id")
    op.drop_column("encaissements", "reconciled_at")
    op.drop_column("encaissements", "is_reconciled")
