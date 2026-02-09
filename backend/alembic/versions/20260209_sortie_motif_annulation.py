"""add motif_annulation to sorties_fonds

Revision ID: 20260209_sortie_motif_annulation
Revises: 20260209_sortie_statut
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260209_sortie_motif_annulation"
down_revision = "20260209_sortie_statut"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sorties_fonds") as batch:
        batch.add_column(sa.Column("motif_annulation", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sorties_fonds") as batch:
        batch.drop_column("motif_annulation")
