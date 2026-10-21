"""projet ou activité sur les réquisitions et les sorties directes

Un projet ne se rattachait qu'aux encaissements : ses dépenses restaient
introuvables. La réquisition porte désormais le projet (ses sorties en
héritent à la lecture) ; une sortie sans réquisition a son propre champ.
Les deux restent facultatifs.

Revision ID: 20261021a_projet_depenses
Revises: 20261016d_relance_manuelle
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20261021a_projet_depenses"
down_revision = "20261016d_relance_manuelle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("requisitions", "sorties_fonds"):
        op.add_column(
            table,
            sa.Column(
                "project_activity_id",
                sa.Integer(),
                sa.ForeignKey("projets_activites.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_project_activity_id", table, ["project_activity_id"])


def downgrade() -> None:
    for table in ("sorties_fonds", "requisitions"):
        op.drop_index(f"ix_{table}_project_activity_id", table_name=table)
        op.drop_column(table, "project_activity_id")
