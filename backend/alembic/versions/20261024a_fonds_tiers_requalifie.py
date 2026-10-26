"""fonds de tiers requalifiés en recette propre

Un fonds enregistré pour compte de tiers peut se révéler appartenir à
l'organisation qui le détient. Il ne repart pas : il change de nature. Le statut
REQUALIFIE le clôt sans sortie de caisse, la trace de la décision vivant dans
`regularisations_budgetaires`.

Revision ID: 20261024a_ft_requalifie
Revises: 20261022c_user_sexe
Create Date: 2026-10-24
"""

from alembic import op


revision = "20261024a_ft_requalifie"
down_revision = "20261022c_user_sexe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_fonds_tiers_statut", "fonds_tiers_operations", type_="check")
    op.create_check_constraint(
        "ck_fonds_tiers_statut",
        "fonds_tiers_operations",
        "statut IN ('OUVERT','PARTIELLEMENT_REMBOURSE','REGULARISE','REQUALIFIE','ANNULE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_fonds_tiers_statut", "fonds_tiers_operations", type_="check")
    op.create_check_constraint(
        "ck_fonds_tiers_statut",
        "fonds_tiers_operations",
        "statut IN ('OUVERT','PARTIELLEMENT_REMBOURSE','REGULARISE','ANNULE')",
    )
