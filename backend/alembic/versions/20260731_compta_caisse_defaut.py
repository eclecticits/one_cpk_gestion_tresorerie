"""Module Comptabilité — compte caisse par défaut sur la société

`compta_societes.compte_caisse_defaut_id` : compte comptable (571) utilisé
pour les opérations en canal CAISSE qui passent par la caisse unique
(`CaisseCentrale`, singleton par organisation), par opposition à un
`CompteBancaire` de type CASH nommé individuellement (caisse progressive),
qui continue de se mapper via `ComptaMappingCompteBancaire`.

Revision ID: 20260731_compta_caisse_defaut
Revises: 20260731_compta_mappings
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_compta_caisse_defaut"
down_revision = "20260731_compta_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compta_societes",
        sa.Column(
            "compte_caisse_defaut_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("compta_societes", "compte_caisse_defaut_id")
