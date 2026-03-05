"""transferts internes

Revision ID: 20260305_transferts_internes
Revises: 20260305_soldes_caisse
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260305_transferts_internes"
down_revision = "20260305_soldes_caisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transferts_internes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("destination_type", sa.String(length=10), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=True),
        sa.Column("montant", sa.Numeric(15, 2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("date_transfert", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("execute_par", sa.UUID(), nullable=True),
    )
    op.create_check_constraint(
        "ck_transferts_internes_source_type",
        "transferts_internes",
        "source_type IN ('CAISSE','BANQUE')",
    )
    op.create_check_constraint(
        "ck_transferts_internes_destination_type",
        "transferts_internes",
        "destination_type IN ('CAISSE','BANQUE')",
    )
    op.create_check_constraint(
        "ck_transferts_internes_devise",
        "transferts_internes",
        "devise IN ('USD','CDF')",
    )
    op.create_check_constraint(
        "ck_transferts_internes_source_ref",
        "transferts_internes",
        "(source_type = 'CAISSE' AND source_id IS NULL) OR "
        "(source_type = 'BANQUE' AND source_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_transferts_internes_destination_ref",
        "transferts_internes",
        "(destination_type = 'CAISSE' AND destination_id IS NULL) OR "
        "(destination_type = 'BANQUE' AND destination_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_table("transferts_internes")
