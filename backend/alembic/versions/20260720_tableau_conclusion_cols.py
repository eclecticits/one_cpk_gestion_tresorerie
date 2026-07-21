"""Colonnes de délibération pour les dossiers Tableau.

Promeut en vraies colonnes SQL les champs auparavant stockés dans `raw_data` :
conclusion (verdict), motif, chiffre d'affaires, date de naissance, âge, NIF,
ancienneté, sexe.

Revision ID: 20260720_tableau_conclusion_cols
Revises: 20260719_sortie_directe_priv
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_tableau_conclusion_cols"
down_revision = "20260719_sortie_directe_priv"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_dossiers"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("chiffre_affaires", sa.Boolean(), nullable=True))
    op.add_column(TABLE, sa.Column("sexe", sa.String(length=10), nullable=True))
    op.add_column(TABLE, sa.Column("date_naissance", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("age", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("nif", sa.String(length=50), nullable=True))
    op.add_column(TABLE, sa.Column("anciennete", sa.String(length=30), nullable=True))
    op.add_column(TABLE, sa.Column("conclusion", sa.String(length=30), nullable=True))
    op.add_column(TABLE, sa.Column("conclusion_motif", sa.Text(), nullable=True))
    op.create_index(
        "ix_secretariat_tableau_dossiers_conclusion", TABLE, ["conclusion"]
    )


def downgrade() -> None:
    op.drop_index("ix_secretariat_tableau_dossiers_conclusion", table_name=TABLE)
    op.drop_column(TABLE, "conclusion_motif")
    op.drop_column(TABLE, "conclusion")
    op.drop_column(TABLE, "anciennete")
    op.drop_column(TABLE, "nif")
    op.drop_column(TABLE, "age")
    op.drop_column(TABLE, "date_naissance")
    op.drop_column(TABLE, "sexe")
    op.drop_column(TABLE, "chiffre_affaires")
