"""projet ou activité sur les sorties directes programmées

Le projet d'une sortie directe ne se choisissait qu'à la caisse, au paiement :
celui qui programme la dépense, et sait ce qu'elle finance, ne pouvait pas le
dire. L'ordre le porte désormais, facultatif ; la sortie payée en hérite.

Revision ID: 20261028a_projet_ordre_direct
Revises: 20261027_compta_export_bank
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20261028a_projet_ordre_direct"
down_revision = "20261027_compta_export_bank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordres_decaissement",
        sa.Column(
            "project_activity_id",
            sa.Integer(),
            sa.ForeignKey("projets_activites.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ordres_decaissement_project_activity_id", "ordres_decaissement", ["project_activity_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ordres_decaissement_project_activity_id", table_name="ordres_decaissement")
    op.drop_column("ordres_decaissement", "project_activity_id")
