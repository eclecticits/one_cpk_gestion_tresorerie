"""Add proforma fields to encaissements.

Revision ID: 20260408_proforma_encaissements
Revises: 20260401_remboursement_pdf_path
Create Date: 2026-04-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_proforma_encaissements"
down_revision = "20260401_remboursement_pdf_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissements",
        sa.Column("est_proforma", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "encaissements",
        sa.Column("numero_proforma", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "encaissements",
        sa.Column("date_paiement", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "encaissements",
        sa.Column("source_proforma_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_encaissements_source_proforma",
        "encaissements",
        "encaissements",
        ["source_proforma_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("UPDATE encaissements SET est_proforma = false WHERE est_proforma IS DISTINCT FROM false;")

    op.alter_column("encaissements", "numero_recu", nullable=True)


def downgrade() -> None:
    op.alter_column("encaissements", "numero_recu", nullable=False)
    op.drop_constraint("fk_encaissements_source_proforma", "encaissements", type_="foreignkey")
    op.drop_column("encaissements", "source_proforma_id")
    op.drop_column("encaissements", "date_paiement")
    op.drop_column("encaissements", "numero_proforma")
    op.drop_column("encaissements", "est_proforma")
