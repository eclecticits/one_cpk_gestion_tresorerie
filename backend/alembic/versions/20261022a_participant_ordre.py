"""ordre d'impression des participants d'un remboursement de transport

Le classement par libellé de fonction laissait derrière les autres membres
ceux dont la fonction n'était pas reconnue (« Membre du bureau »,
« Secrétaire »…). L'ordre de saisie, réglable à la main, prime désormais ;
les remboursements antérieurs, sans ordre, gardent le classement par fonction.

Revision ID: 20261022a_participant_ordre
Revises: 20261021a_projet_depenses
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022a_participant_ordre"
down_revision = "20261021a_projet_depenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participants_transport", sa.Column("ordre", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants_transport", "ordre")
