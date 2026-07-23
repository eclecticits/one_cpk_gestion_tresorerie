"""Contrainte SQL : montant_paye strictement positif sur sorties_fonds.

Dernière ligne de défense contre les montants négatifs (qui créditeraient la
trésorerie au lieu de la débiter). La contrainte est créée NOT VALID pour ne
pas bloquer la migration si des lignes historiques à 0 existent ; les
nouvelles écritures sont contrôlées immédiatement.

Revision ID: 20260722c_sortie_montant_positif
Revises: 20260722b_relance_limits
Create Date: 2026-07-22
"""

from alembic import op


revision = "20260722c_sortie_montant_positif"
down_revision = "20260722b_relance_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sorties_fonds
        ADD CONSTRAINT ck_sorties_fonds_montant_paye_positif
        CHECK (montant_paye > 0) NOT VALID
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sorties_fonds DROP CONSTRAINT IF EXISTS ck_sorties_fonds_montant_paye_positif"
    )
