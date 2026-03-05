"""soldes caisse comptes et devise sorties

Revision ID: 20260305_soldes_caisse
Revises: 20260305_banques_comptes
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260305_soldes_caisse"
down_revision = "20260305_banques_comptes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comptes_bancaires",
        sa.Column("solde_actuel", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )
    op.execute("UPDATE comptes_bancaires SET solde_actuel = solde_initial WHERE solde_actuel = 0")

    op.add_column(
        "sorties_fonds",
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
    )
    op.create_check_constraint(
        "ck_sorties_fonds_devise",
        "sorties_fonds",
        "devise IN ('USD','CDF')",
    )

    op.create_table(
        "caisse_centrale",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("solde_usd", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("solde_cdf", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("derniere_maj", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute("INSERT INTO caisse_centrale (solde_usd, solde_cdf) VALUES (0, 0)")


def downgrade() -> None:
    op.drop_table("caisse_centrale")
    op.drop_constraint("ck_sorties_fonds_devise", "sorties_fonds", type_="check")
    op.drop_column("sorties_fonds", "devise")
    op.drop_column("comptes_bancaires", "solde_actuel")
