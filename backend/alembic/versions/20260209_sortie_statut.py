"""add statut to sorties_fonds

Revision ID: 20260209_sortie_statut
Revises: 20260209_sortie_security
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260209_sortie_statut"
down_revision = "20260209_sortie_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sorties_fonds") as batch:
        batch.add_column(sa.Column("statut", sa.String(length=20), nullable=False, server_default="VALIDE"))


def downgrade() -> None:
    with op.batch_alter_table("sorties_fonds") as batch:
        batch.drop_column("statut")
