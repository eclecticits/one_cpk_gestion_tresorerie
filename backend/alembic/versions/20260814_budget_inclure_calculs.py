"""poste budgetaire : inclure ou non dans les calculs

Revision ID: 20260814_budget_incl_calc
Revises: 20260814_budget_comm_gen
Create Date: 2026-08-14 11:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260814_budget_incl_calc"
down_revision = "20260814_budget_comm_gen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default true : l'existant garde le comportement actuel, seules les
    # lignes explicitement exclues (report d'exercice anterieur, ligne pour
    # memoire) sortiront des totaux.
    op.add_column(
        "budget_postes",
        sa.Column(
            "inclure_dans_calculs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("budget_postes", "inclure_dans_calculs")
