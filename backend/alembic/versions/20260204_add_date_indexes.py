"""add date indexes for dashboard queries

Revision ID: 20260204_add_date_indexes
Revises: 0009_print_settings_assets, 20250201_remb_transport
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260204_add_date_indexes"
down_revision = ("0009_print_settings_assets", "20250201_remb_transport")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_encaissements_date_encaissement ON public.encaissements(date_encaissement);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sorties_fonds_date_paiement ON public.sorties_fonds(date_paiement);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sorties_fonds_date_paiement;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_date_encaissement;")
