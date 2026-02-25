"""add encaissement libelle presets to print settings

Revision ID: 20260225_add_enc_libelle_presets
Revises: 20260225_add_enc_libelle
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260225_add_enc_libelle_presets"
down_revision = "20260225_add_enc_libelle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("encaissement_libelle_presets", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("print_settings", "encaissement_libelle_presets", server_default=None)


def downgrade() -> None:
    op.drop_column("print_settings", "encaissement_libelle_presets")
