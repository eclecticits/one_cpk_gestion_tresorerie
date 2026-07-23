"""Encadrement des relances de solde : compteur et date par encaissement.

- relance_count : nombre de relances déjà envoyées (plafond appliqué côté API).
- derniere_relance_le : date de la dernière relance (délai minimum entre deux).

Revision ID: 20260722b_relance_limits
Revises: 20260722a_clients
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722b_relance_limits"
down_revision = "20260722a_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissements",
        sa.Column("relance_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "encaissements",
        sa.Column("derniere_relance_le", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("encaissements", "derniere_relance_le")
    op.drop_column("encaissements", "relance_count")
