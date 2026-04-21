"""Separate SaaS and tenant payment flows.

Revision ID: 20260421_payment_flow_split
Revises: 20260408_proforma_encaissements
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_payment_flow_split"
down_revision = "20260408_proforma_encaissements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column("flow", sa.String(length=30), nullable=False, server_default="TENANT_BUSINESS"),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("beneficiary_type", sa.String(length=20), nullable=False, server_default="TENANT"),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("beneficiary_organisation_id", sa.Integer(), nullable=True),
    )
    op.add_column("payment_transactions", sa.Column("merchant_account_ref", sa.String(length=120), nullable=True))
    op.add_column("payment_transactions", sa.Column("source_type", sa.String(length=60), nullable=True))
    op.add_column("payment_transactions", sa.Column("source_id", sa.String(length=120), nullable=True))
    op.execute(
        """
        UPDATE payment_transactions
        SET beneficiary_organisation_id = organisation_id
        WHERE beneficiary_organisation_id IS NULL
        """
    )
    op.create_index(
        "ix_payment_transactions_beneficiary_organisation_id",
        "payment_transactions",
        ["beneficiary_organisation_id"],
    )
    op.create_foreign_key(
        "fk_payment_transactions_beneficiary_org",
        "payment_transactions",
        "organisations",
        ["beneficiary_organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_payment_tx_flow",
        "payment_transactions",
        "flow IN ('TENANT_BUSINESS','SAAS_SUBSCRIPTION')",
    )
    op.create_check_constraint(
        "ck_payment_tx_beneficiary_type",
        "payment_transactions",
        "beneficiary_type IN ('TENANT','PLATFORM')",
    )

    op.add_column(
        "transactions",
        sa.Column("flow", sa.String(length=30), nullable=False, server_default="SAAS_SUBSCRIPTION"),
    )
    op.add_column(
        "transactions",
        sa.Column("beneficiary_type", sa.String(length=20), nullable=False, server_default="PLATFORM"),
    )
    op.add_column("transactions", sa.Column("beneficiary_organisation_id", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("merchant_account_ref", sa.String(length=120), nullable=True))
    op.create_index("ix_transactions_beneficiary_organisation_id", "transactions", ["beneficiary_organisation_id"])
    op.create_check_constraint(
        "ck_transactions_flow",
        "transactions",
        "flow IN ('SAAS_SUBSCRIPTION')",
    )
    op.create_check_constraint(
        "ck_transactions_beneficiary_type",
        "transactions",
        "beneficiary_type IN ('PLATFORM')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_beneficiary_type", "transactions", type_="check")
    op.drop_constraint("ck_transactions_flow", "transactions", type_="check")
    op.drop_index("ix_transactions_beneficiary_organisation_id", table_name="transactions")
    op.drop_column("transactions", "merchant_account_ref")
    op.drop_column("transactions", "beneficiary_organisation_id")
    op.drop_column("transactions", "beneficiary_type")
    op.drop_column("transactions", "flow")

    op.drop_constraint("ck_payment_tx_beneficiary_type", "payment_transactions", type_="check")
    op.drop_constraint("ck_payment_tx_flow", "payment_transactions", type_="check")
    op.drop_constraint("fk_payment_transactions_beneficiary_org", "payment_transactions", type_="foreignkey")
    op.drop_index("ix_payment_transactions_beneficiary_organisation_id", table_name="payment_transactions")
    op.drop_column("payment_transactions", "source_id")
    op.drop_column("payment_transactions", "source_type")
    op.drop_column("payment_transactions", "merchant_account_ref")
    op.drop_column("payment_transactions", "beneficiary_organisation_id")
    op.drop_column("payment_transactions", "beneficiary_type")
    op.drop_column("payment_transactions", "flow")
