"""commentaire general de l'exercice budgetaire (un par vue)

Revision ID: 20260814_budget_comm_gen
Revises: 20260813_view_cancelled_ops
Create Date: 2026-08-14 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260814_budget_comm_gen"
down_revision = "20260813_view_cancelled_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deux colonnes plutot qu'une : l'export des depenses et celui des recettes
    # sont deux documents distincts, chacun porte sa propre justification.
    op.add_column(
        "budget_exercices",
        sa.Column("commentaire_general_depense", sa.Text(), nullable=True),
    )
    op.add_column(
        "budget_exercices",
        sa.Column("commentaire_general_recette", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("budget_exercices", "commentaire_general_recette")
    op.drop_column("budget_exercices", "commentaire_general_depense")
