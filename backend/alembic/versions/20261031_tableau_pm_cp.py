"""champs des modèles Membres PP/PM des conseils provinciaux

Revision ID: 20261031_tableau_pm_cp
Revises: 20261029b_sorties_banque
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_tableau_pm_cp"
down_revision = "20261029b_sorties_banque"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tableau_personne_physique_snapshots",
        sa.Column("province_attache", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "tableau_personne_morale_snapshots",
        sa.Column("associe_gerant", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "tableau_personne_morale_snapshots",
        sa.Column("sigle", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "tableau_personne_morale_snapshots",
        sa.Column("raison_sociale", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "tableau_personne_morale_snapshots",
        sa.Column("lieu_creation", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "tableau_personne_morale_snapshots",
        sa.Column("province_attache", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tableau_personne_morale_snapshots", "province_attache")
    op.drop_column("tableau_personne_morale_snapshots", "lieu_creation")
    op.drop_column("tableau_personne_morale_snapshots", "raison_sociale")
    op.drop_column("tableau_personne_morale_snapshots", "sigle")
    op.drop_column("tableau_personne_morale_snapshots", "associe_gerant")
    op.drop_column("tableau_personne_physique_snapshots", "province_attache")
