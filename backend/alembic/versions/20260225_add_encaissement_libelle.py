"""add libelle to encaissements

Revision ID: 20260225_add_enc_libelle
Revises: bd2e20e4a9c9
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260225_add_enc_libelle"
down_revision = "bd2e20e4a9c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("libelle", sa.String(length=255), nullable=True))
    op.execute("UPDATE encaissements SET libelle = 'Libellé non renseigné' WHERE libelle IS NULL")
    op.alter_column("encaissements", "libelle", nullable=False)


def downgrade() -> None:
    op.drop_column("encaissements", "libelle")
