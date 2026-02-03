"""create sorties_fonds table

Revision ID: 0007_sorties_fonds_table
Revises: 0006_merge_heads
Create Date: 2026-01-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0007_sorties_fonds_table"
down_revision = "0006_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sorties_fonds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type_sortie", sa.String(length=50), nullable=False),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rubrique_code", sa.String(length=50), nullable=True),
        sa.Column("montant_paye", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("date_paiement", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode_paiement", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("motif", sa.Text(), nullable=False),
        sa.Column("beneficiaire", sa.String(length=200), nullable=False),
        sa.Column("piece_justificative", sa.String(length=200), nullable=True),
        sa.Column("commentaire", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sorties_fonds_requisition_id", "sorties_fonds", ["requisition_id"])
    op.create_index("ix_sorties_fonds_created_by", "sorties_fonds", ["created_by"])
    op.create_index("ix_sorties_fonds_date_paiement", "sorties_fonds", ["date_paiement"])


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_date_paiement", table_name="sorties_fonds")
    op.drop_index("ix_sorties_fonds_created_by", table_name="sorties_fonds")
    op.drop_index("ix_sorties_fonds_requisition_id", table_name="sorties_fonds")
    op.drop_table("sorties_fonds")
