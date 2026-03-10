"""add card mode for encaissements

Revision ID: 20260306_enc_mode_card
Revises: 20260305_weekly_report_last_sf
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op


revision = "20260306_enc_mode_card"
down_revision = "20260305_weekly_report_last_sf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_encaissements_mode_paiement", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_mode_paiement",
        "encaissements",
        "mode_paiement IN ('cash','mobile_money','virement','card')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_encaissements_mode_paiement", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_mode_paiement",
        "encaissements",
        "mode_paiement IN ('cash','mobile_money','virement')",
    )
