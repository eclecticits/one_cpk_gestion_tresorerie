"""Tableau : source d'import « BilanForco »

Revision ID: 20261113_tableau_bilan_forco
Revises: 20261113_canal_progressif

La synthèse des bilans de formation continue sur quatre ans (formations,
heures déclarées, heures validées, cumul et taux d'atteinte des 120 heures)
devient une source d'import à part entière. La contrainte sur `source_type`
énumère les sources admises : elle est élargie d'une valeur.
"""

from __future__ import annotations

from alembic import op


revision = "20261113_tableau_bilan_forco"
down_revision = "20261113_canal_progressif"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_imports"
CONTRAINTE = "ck_tableau_import_source_type"
AVANT = "'personnes_physiques', 'personnes_morales', 'chiffres_affaires', 'assurances', 'tableau'"
APRES = "'personnes_physiques', 'personnes_morales', 'chiffres_affaires', 'assurances', 'bilan_forco', 'tableau'"


def upgrade() -> None:
    op.drop_constraint(CONTRAINTE, TABLE, type_="check")
    op.create_check_constraint(CONTRAINTE, TABLE, f"source_type IN ({APRES})")


def downgrade() -> None:
    # Échoue tant qu'un import BilanForco existe : c'est voulu, on ne supprime
    # pas des imports pour revenir en arrière.
    op.drop_constraint(CONTRAINTE, TABLE, type_="check")
    op.create_check_constraint(CONTRAINTE, TABLE, f"source_type IN ({AVANT})")
