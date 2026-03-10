"""payment transactions table

Revision ID: 20260306_payment_tx
Revises: 20260306_enc_mode_card
Create Date: 2026-03-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260306_payment_tx"
down_revision = "20260306_enc_mode_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("provider_ref", sa.String(length=120), nullable=False, unique=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("fees", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encaissements.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_check_constraint(
        "ck_payment_tx_status",
        "payment_transactions",
        "status IN ('PENDING','SUCCESS','FAILED')",
    )
    op.create_check_constraint(
        "ck_payment_tx_method",
        "payment_transactions",
        "method IN ('MOMO_AIRTEL','MOMO_MPESA','MOMO_ORANGE','VISA')",
    )
    op.create_check_constraint(
        "ck_payment_tx_currency",
        "payment_transactions",
        "currency IN ('USD','CDF')",
    )
    op.create_index(
        "ix_payment_transactions_encaissement_id",
        "payment_transactions",
        ["encaissement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_transactions_encaissement_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")
