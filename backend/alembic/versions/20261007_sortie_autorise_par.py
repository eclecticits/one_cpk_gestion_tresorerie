"""bon sur requisition : « Autorise par » ou signature de l'autorite

Revision ID: 20261007_sortie_autorise_par
Revises: 20261007_bon_sortie_directe
Create Date: 2026-10-07

Le bon d'une sortie sur requisition ne porte plus le nom d'une personne dans
son cadre d'autorisation : c'est l'instance (« LE BUREAU » par defaut) qui a
autorise. Les noms restent dans le circuit de validation imprime.

L'administrateur choisit ce que le bon montre de l'autorisation : la mention
seule (deux signatures), la signature de l'autorite, ou les deux.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261007_sortie_autorise_par"
down_revision = "20261007_bon_sortie_directe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("sortie_autorise_par", sa.String(length=200), nullable=False, server_default="LE BUREAU"),
    )
    op.add_column(
        "print_settings",
        sa.Column("sortie_req_autorisation", sa.String(length=30), nullable=False, server_default="mention"),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "sortie_req_autorisation")
    op.drop_column("print_settings", "sortie_autorise_par")
