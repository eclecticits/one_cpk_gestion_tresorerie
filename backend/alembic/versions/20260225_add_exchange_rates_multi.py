"""add multi exchange rates to print settings

Revision ID: 20260225_add_exchange_multi
Revises: 20260225_seed_enc_libelle
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260225_add_exchange_multi"
down_revision = "20260225_seed_enc_libelle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("exchange_rate_cdf", sa.Numeric(12, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "print_settings",
        sa.Column("exchange_rate_eur", sa.Numeric(12, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "print_settings",
        sa.Column("exchange_rate_xof", sa.Numeric(12, 4), nullable=False, server_default="0"),
    )
    op.execute("UPDATE print_settings SET exchange_rate_cdf = exchange_rate")
    op.alter_column("print_settings", "exchange_rate_cdf", server_default=None)
    op.alter_column("print_settings", "exchange_rate_eur", server_default=None)
    op.alter_column("print_settings", "exchange_rate_xof", server_default=None)


def downgrade() -> None:
    op.drop_column("print_settings", "exchange_rate_xof")
    op.drop_column("print_settings", "exchange_rate_eur")
    op.drop_column("print_settings", "exchange_rate_cdf")
