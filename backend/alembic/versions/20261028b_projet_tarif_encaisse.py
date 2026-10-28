"""projet ou activité proposé par un libellé d'encaissement

Le projet d'un encaissement se choisissait à la main, à chaque reçu, alors que
la plupart des libellés financent toujours le même projet. Le tarif le porte
désormais, facultatif : il est proposé à la saisie, jamais imposé.

Revision ID: 20261028b_projet_tarif_encaisse
Revises: 20261028a_projet_ordre_direct
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20261028b_projet_tarif_encaisse"
down_revision = "20261028a_projet_ordre_direct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissement_tarifs",
        sa.Column(
            "project_activity_id",
            sa.Integer(),
            sa.ForeignKey("projets_activites.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_encaissement_tarifs_project_activity_id", "encaissement_tarifs", ["project_activity_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_encaissement_tarifs_project_activity_id", table_name="encaissement_tarifs")
    op.drop_column("encaissement_tarifs", "project_activity_id")
