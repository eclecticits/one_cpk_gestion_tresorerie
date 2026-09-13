"""Ajoute l'année d'inscription et l'ancienneté aux dossiers Tableau.

Revision ID: 20260913_tableau_anciennete
Revises: 20260912_clients_sexe
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260913_tableau_anciennete"
down_revision = "20260912_clients_sexe"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_dossiers"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("annee_inscription", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("anciennete_annees", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "anciennete_annees")
    op.drop_column(TABLE, "annee_inscription")
