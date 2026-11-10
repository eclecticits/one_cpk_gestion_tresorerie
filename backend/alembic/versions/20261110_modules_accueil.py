"""Module d'arrivée après la connexion

Revision ID: 20261110_modules_accueil
Revises: 20261107_tableau_releve_lots

L'organisation fixe l'ordre de priorité des modules ; un utilisateur peut avoir
son propre module d'accueil, qui passe avant cet ordre. Les deux sont
facultatifs : NULL garde l'ordre par défaut.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261110_modules_accueil"
down_revision = "20261107_tableau_releve_lots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organisation_settings", sa.Column("modules_priorite", postgresql.JSONB(), nullable=True))
    op.add_column("users", sa.Column("module_accueil", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "module_accueil")
    op.drop_column("organisation_settings", "modules_priorite")
