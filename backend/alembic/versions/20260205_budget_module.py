"""ajout tables budget

Revision ID: 20260205_budget_module
Revises: 20260204_add_date_indexes
Create Date: 2026-02-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260205_budget_module"
down_revision = "20260204_add_date_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statut_enum = sa.Enum("Brouillon", "Vot\u00e9", "Cl\u00f4tur\u00e9", name="statut_budget")

    op.create_table(
        "budget_exercices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("annee", sa.Integer(), nullable=False),
        sa.Column("statut", statut_enum, nullable=False, server_default="Brouillon"),
        sa.UniqueConstraint("annee", name="uq_budget_exercices_annee"),
    )
    op.create_index("ix_budget_exercices_annee", "budget_exercices", ["annee"])

    op.create_table(
        "budget_lignes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("exercice_id", sa.Integer(), sa.ForeignKey("budget_exercices.id"), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=True),
        sa.Column("montant_prevu", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("montant_engage", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("montant_paye", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_budget_lignes_exercice_id", "budget_lignes", ["exercice_id"])
    op.create_index("ix_budget_lignes_code", "budget_lignes", ["code"])


def downgrade() -> None:
    op.drop_index("ix_budget_lignes_code", table_name="budget_lignes")
    op.drop_index("ix_budget_lignes_exercice_id", table_name="budget_lignes")
    op.drop_table("budget_lignes")

    op.drop_index("ix_budget_exercices_annee", table_name="budget_exercices")
    op.drop_table("budget_exercices")

    statut_enum = sa.Enum("Brouillon", "Vot\u00e9", "Cl\u00f4tur\u00e9", name="statut_budget")
    statut_enum.drop(op.get_bind(), checkfirst=True)
