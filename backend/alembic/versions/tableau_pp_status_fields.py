"""Champs contextuels des snapshots PP préparatoires."""
from alembic import op
import sqlalchemy as sa

revision = "tableau_pp_status_fields"
down_revision = "tableau_ca_declarations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tableau_personne_physique_snapshots", sa.Column("cabinet_attache", sa.String(150), nullable=True))
    op.add_column("tableau_personne_physique_snapshots", sa.Column("nif", sa.String(100), nullable=True))
    op.add_column("tableau_personne_physique_snapshots", sa.Column("nom_employeur", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("tableau_personne_physique_snapshots", "nom_employeur")
    op.drop_column("tableau_personne_physique_snapshots", "nif")
    op.drop_column("tableau_personne_physique_snapshots", "cabinet_attache")
