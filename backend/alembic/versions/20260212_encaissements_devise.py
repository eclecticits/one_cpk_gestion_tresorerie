"""add devise perception fields on encaissements

Revision ID: 20260212_encaissements_devise
Revises: 20260212_denominations
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_encaissements_devise"
down_revision = "20260212_denominations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("montant_percu", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("encaissements", sa.Column("devise_perception", sa.String(length=10), nullable=False, server_default="USD"))
    op.add_column("encaissements", sa.Column("taux_change_applique", sa.Numeric(12, 4), nullable=False, server_default="1"))

    op.execute("UPDATE encaissements SET montant_percu = COALESCE(montant_paye, 0) WHERE montant_percu = 0")

    op.alter_column("encaissements", "montant_percu", server_default=None)
    op.alter_column("encaissements", "devise_perception", server_default=None)
    op.alter_column("encaissements", "taux_change_applique", server_default=None)


def downgrade() -> None:
    op.drop_column("encaissements", "taux_change_applique")
    op.drop_column("encaissements", "devise_perception")
    op.drop_column("encaissements", "montant_percu")
