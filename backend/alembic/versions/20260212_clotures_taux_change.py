"""add taux_change to clotures

Revision ID: 20260212_clotures_taux_change
Revises: 20260212_encaissements_devise
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_clotures_taux_change"
down_revision = "20260212_encaissements_devise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clotures",
        sa.Column("taux_change_applique", sa.Numeric(12, 4), nullable=False, server_default="1"),
    )
    op.alter_column("clotures", "taux_change_applique", server_default=None)


def downgrade() -> None:
    op.drop_column("clotures", "taux_change_applique")
