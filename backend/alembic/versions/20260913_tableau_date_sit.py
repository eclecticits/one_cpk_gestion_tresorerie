"""Ajoute la date métier de situation des imports Tableau.

Revision ID: 20260913_tableau_date_sit
Revises: 20260913_tableau_anciennete
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260913_tableau_date_sit"
down_revision = "20260913_tableau_anciennete"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_imports"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("date_situation", sa.Date(), nullable=True))
    op.create_index("ix_secretariat_tableau_imports_date_situation", TABLE, ["date_situation"])


def downgrade() -> None:
    op.drop_index("ix_secretariat_tableau_imports_date_situation", table_name=TABLE)
    op.drop_column(TABLE, "date_situation")
