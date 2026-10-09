"""copie des emails de paiement

Revision ID: 20261009_paiement_cc
Revises: 20261008_changement_canal
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20261009_paiement_cc"
down_revision = "20261008_changement_canal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("emails_paiement_cc", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "emails_paiement_cc")
