"""tracer la modification d'un commentaire budgetaire

Revision ID: 20260813_budget_comment_edit
Revises: 20260813_budget_commentaires
Create Date: 2026-08-13 13:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260813_budget_comment_edit"
down_revision = "20260813_budget_commentaires"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Un commentaire reste modifiable tant que l'exercice est au brouillon. La
    # date de modification rend le fait visible : un texte retouche sans trace
    # laisserait croire que c'est la redaction d'origine.
    op.add_column(
        "budget_poste_commentaires",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("budget_poste_commentaires", "updated_at")
