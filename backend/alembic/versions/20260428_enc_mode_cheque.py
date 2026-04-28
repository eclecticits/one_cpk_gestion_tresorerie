"""Add cheque payment mode for encaissements.

Revision ID: 20260428_enc_mode_cheque
Revises: 20260427_sysset_uc
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op


revision = "20260428_enc_mode_cheque"
down_revision = "20260427_sysset_uc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_encaissements_mode_paiement", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_mode_paiement",
        "encaissements",
        "mode_paiement IN ('cash','mobile_money','virement','card','cheque')",
    )
    op.drop_constraint("ck_payment_history_mode_paiement", "payment_history", type_="check")
    op.create_check_constraint(
        "ck_payment_history_mode_paiement",
        "payment_history",
        "mode_paiement IN ('cash','mobile_money','virement','card','cheque')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_history_mode_paiement", "payment_history", type_="check")
    op.create_check_constraint(
        "ck_payment_history_mode_paiement",
        "payment_history",
        "mode_paiement IN ('cash','mobile_money','virement')",
    )
    op.drop_constraint("ck_encaissements_mode_paiement", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_mode_paiement",
        "encaissements",
        "mode_paiement IN ('cash','mobile_money','virement','card')",
    )
