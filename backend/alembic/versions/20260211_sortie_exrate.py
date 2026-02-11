"""add exchange rate snapshot to sorties_fonds

Revision ID: 20260211_sortie_exrate
Revises: 20260211_recu_numero_padding
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260211_sortie_exrate"
down_revision = "20260211_recu_numero_padding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sorties_fonds", sa.Column("exchange_rate_snapshot", sa.Numeric(12, 4), nullable=True))
    op.execute(
        """
        UPDATE sorties_fonds
        SET exchange_rate_snapshot = (
            SELECT exchange_rate FROM print_settings ORDER BY id ASC LIMIT 1
        )
        WHERE exchange_rate_snapshot IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_column("sorties_fonds", "exchange_rate_snapshot")
