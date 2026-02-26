"""add annulee_le to sorties_fonds

Revision ID: 20260226_add_sortie_annulee_le
Revises: 20260225_seed_enc_libelle
Create Date: 2026-02-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260226_add_sortie_annulee_le"
down_revision = "20260225_seed_enc_libelle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sorties_fonds",
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sorties_fonds", "annulee_le")
