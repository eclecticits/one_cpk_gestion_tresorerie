"""requisitions tables

Revision ID: 0005_requisitions_tables
Revises: 0004_encaissements_constraints
Create Date: 2026-01-29 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0005_requisitions_tables"
down_revision = "0004_encaissements_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requisitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("numero_requisition", sa.String(length=50), nullable=False),
        sa.Column("objet", sa.Text(), nullable=False),
        sa.Column("mode_paiement", sa.String(length=50), nullable=False),
        sa.Column("type_requisition", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("montant_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validee_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approuvee_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approuvee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payee_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motif_rejet", sa.Text(), nullable=True),
        sa.Column("a_valoir", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("instance_beneficiaire", sa.String(length=200), nullable=True),
        sa.Column("notes_a_valoir", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("numero_requisition", name="uq_requisitions_numero"),
    )
    op.create_index("ix_requisitions_numero", "requisitions", ["numero_requisition"])
    op.create_index("ix_requisitions_status", "requisitions", ["status"])
    op.create_index("ix_requisitions_created_by", "requisitions", ["created_by"])

    op.create_table(
        "lignes_requisition",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubrique", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantite", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("montant_unitaire", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("montant_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_lignes_requisition_requisition_id", "lignes_requisition", ["requisition_id"])


def downgrade() -> None:
    op.drop_index("ix_lignes_requisition_requisition_id", table_name="lignes_requisition")
    op.drop_table("lignes_requisition")
    op.drop_index("ix_requisitions_created_by", table_name="requisitions")
    op.drop_index("ix_requisitions_status", table_name="requisitions")
    op.drop_index("ix_requisitions_numero", table_name="requisitions")
    op.drop_table("requisitions")
