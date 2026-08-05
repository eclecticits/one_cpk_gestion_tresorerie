"""Autorise les brouillons de sorties de fonds

Revision ID: 20260803_sortie_drafts
Revises: 20260803_bank_details
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op


revision = "20260803_sortie_drafts"
down_revision = "20260803_bank_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sorties_fonds_montant_paye_positif",
        "sorties_fonds",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sorties_fonds_montant_paye_positif",
        "sorties_fonds",
        "(statut = 'BROUILLON' AND montant_paye >= 0) OR montant_paye > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sorties_fonds_montant_paye_positif",
        "sorties_fonds",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sorties_fonds_montant_paye_positif",
        "sorties_fonds",
        "montant_paye > 0",
    )
