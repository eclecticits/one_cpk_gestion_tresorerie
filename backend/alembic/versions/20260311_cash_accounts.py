"""cash accounts and account type

Revision ID: 20260311_cash_accounts
Revises: 20260310_saas_metrics
Create Date: 2026-03-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260311_cash_accounts"
down_revision = "20260310_saas_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comptes_bancaires",
        sa.Column("account_type", sa.String(length=10), nullable=False, server_default="BANK"),
    )
    op.alter_column("comptes_bancaires", "banque_id", nullable=True)

    op.create_check_constraint(
        "ck_comptes_bancaires_account_type",
        "comptes_bancaires",
        "account_type IN ('BANK','CASH')",
    )
    op.create_check_constraint(
        "ck_comptes_bancaires_bank_ref",
        "comptes_bancaires",
        "(account_type = 'BANK' AND banque_id IS NOT NULL) OR (account_type = 'CASH' AND banque_id IS NULL)",
    )

    op.execute(
        """
        INSERT INTO comptes_bancaires (
            organisation_id,
            banque_id,
            intitule,
            numero_compte,
            devise,
            solde_initial,
            solde_actuel,
            is_active,
            account_type
        )
        SELECT
            o.id,
            NULL,
            'Caisse USD',
            'CASH-USD-' || o.id,
            'USD',
            0,
            0,
            TRUE,
            'CASH'
        FROM organisations o
        WHERE NOT EXISTS (
            SELECT 1 FROM comptes_bancaires cb
            WHERE cb.organisation_id = o.id
              AND cb.account_type = 'CASH'
              AND cb.devise = 'USD'
        )
        """
    )
    op.execute(
        """
        INSERT INTO comptes_bancaires (
            organisation_id,
            banque_id,
            intitule,
            numero_compte,
            devise,
            solde_initial,
            solde_actuel,
            is_active,
            account_type
        )
        SELECT
            o.id,
            NULL,
            'Caisse CDF',
            'CASH-CDF-' || o.id,
            'CDF',
            0,
            0,
            TRUE,
            'CASH'
        FROM organisations o
        WHERE NOT EXISTS (
            SELECT 1 FROM comptes_bancaires cb
            WHERE cb.organisation_id = o.id
              AND cb.account_type = 'CASH'
              AND cb.devise = 'CDF'
        )
        """
    )

    op.drop_constraint("ck_encaissements_compte_bancaire", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_compte_bancaire",
        "encaissements",
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR (canal = 'CAISSE')",
    )

    op.drop_constraint("ck_sorties_fonds_compte_bancaire", "sorties_fonds", type_="check")
    op.create_check_constraint(
        "ck_sorties_fonds_compte_bancaire",
        "sorties_fonds",
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR (canal = 'CAISSE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sorties_fonds_compte_bancaire", "sorties_fonds", type_="check")
    op.create_check_constraint(
        "ck_sorties_fonds_compte_bancaire",
        "sorties_fonds",
        "(canal = 'CAISSE' AND compte_bancaire_id IS NULL) OR "
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL)",
    )

    op.drop_constraint("ck_encaissements_compte_bancaire", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_compte_bancaire",
        "encaissements",
        "(canal = 'CAISSE' AND compte_bancaire_id IS NULL) OR "
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL)",
    )

    op.execute(
        "DELETE FROM comptes_bancaires WHERE account_type = 'CASH'"
    )
    op.drop_constraint("ck_comptes_bancaires_bank_ref", "comptes_bancaires", type_="check")
    op.drop_constraint("ck_comptes_bancaires_account_type", "comptes_bancaires", type_="check")
    op.alter_column("comptes_bancaires", "banque_id", nullable=False)
    op.drop_column("comptes_bancaires", "account_type")
