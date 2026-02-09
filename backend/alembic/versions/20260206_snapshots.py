"""snapshot signatories on approval

Revision ID: 20260206_snapshots
Revises: 20260206_std_print_settings
Create Date: 2026-02-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260206_snapshots"
down_revision = "20260206_std_print_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("requisitions") as batch:
        batch.add_column(sa.Column("req_titre_officiel_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("req_label_gauche_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("req_nom_gauche_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("req_label_droite_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("req_nom_droite_hist", sa.String(length=200), nullable=True))

    with op.batch_alter_table("remboursements_transport") as batch:
        batch.add_column(sa.Column("trans_titre_officiel_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("trans_label_gauche_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("trans_nom_gauche_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("trans_label_droite_hist", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("trans_nom_droite_hist", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("remboursements_transport") as batch:
        batch.drop_column("trans_nom_droite_hist")
        batch.drop_column("trans_label_droite_hist")
        batch.drop_column("trans_nom_gauche_hist")
        batch.drop_column("trans_label_gauche_hist")
        batch.drop_column("trans_titre_officiel_hist")

    with op.batch_alter_table("requisitions") as batch:
        batch.drop_column("req_nom_droite_hist")
        batch.drop_column("req_label_droite_hist")
        batch.drop_column("req_nom_gauche_hist")
        batch.drop_column("req_label_gauche_hist")
        batch.drop_column("req_titre_officiel_hist")
