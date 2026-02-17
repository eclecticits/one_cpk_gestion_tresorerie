"""add configurable sortie signature labels

Revision ID: 20260216_sortie_sig_cfg
Revises: 20260216_sortie_annex
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260216_sortie_sig_cfg"
down_revision = "20260216_sortie_annex"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("sortie_sig_label_1", sa.String(length=200), nullable=False, server_default="CAISSIER"))
        batch.add_column(sa.Column("sortie_sig_label_2", sa.String(length=200), nullable=False, server_default="COMPTABLE"))
        batch.add_column(sa.Column("sortie_sig_label_3", sa.String(length=200), nullable=False, server_default="AUTORITÉ (TRÉSORERIE)"))
        batch.add_column(sa.Column("sortie_sig_hint", sa.String(length=200), nullable=False, server_default="Signature & date"))


def downgrade() -> None:
    # no-op to avoid data loss
    pass
