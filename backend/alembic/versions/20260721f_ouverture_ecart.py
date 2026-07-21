"""Écart d'ouverture de caisse (fond compté vs solde attendu).

Ajoute à ouvertures_caisse : solde_attendu_usd/cdf et ecart_usd/cdf, pour
tracer la différence entre le fond de caisse compté à l'ouverture et le solde
reporté de la dernière clôture.

Revision ID: 20260721f_ouverture_ecart
Revises: 20260721e_caisse_sessions
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721f_ouverture_ecart"
down_revision = "20260721e_caisse_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("solde_attendu_usd", "solde_attendu_cdf", "ecart_usd", "ecart_cdf"):
        op.add_column(
            "ouvertures_caisse",
            sa.Column(col, sa.Numeric(14, 2), nullable=False, server_default="0"),
        )
    for col in ("solde_attendu_usd", "solde_attendu_cdf", "ecart_usd", "ecart_cdf"):
        op.alter_column("ouvertures_caisse", col, server_default=None)


def downgrade() -> None:
    for col in ("ecart_cdf", "ecart_usd", "solde_attendu_cdf", "solde_attendu_usd"):
        op.drop_column("ouvertures_caisse", col)
