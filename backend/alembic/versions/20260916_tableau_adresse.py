"""Adresse actualisable des sources PP/PM."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260916_tableau_adresse"
down_revision = "20260916_tableau_actual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tableau_personne_physique_snapshots", sa.Column("adresse", sa.Text(), nullable=True))
    op.add_column("tableau_personne_morale_snapshots", sa.Column("adresse", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tableau_personne_morale_snapshots", "adresse")
    op.drop_column("tableau_personne_physique_snapshots", "adresse")
