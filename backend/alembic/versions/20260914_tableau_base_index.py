"""Index servant la base consolidée du Tableau (situation courante par membre).

Revision ID: 20260914_tableau_base_idx
Revises: 20260913_tableau_date_sit
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op


revision = "20260914_tableau_base_idx"
down_revision = "20260913_tableau_date_sit"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_dossiers"
INDEX = "ix_secretariat_tableau_dossiers_base"


def upgrade() -> None:
    # La base consolidée déduplique par (organisation, exercice, n° d'ordre).
    op.create_index(INDEX, TABLE, ["organisation_id", "exercice", "numero_ordre"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
