"""add sortie qr and watermark settings

Revision ID: 20260209_sortie_security
Revises: 20260209_sortie_signataires
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260209_sortie_security"
down_revision = "20260209_sortie_signataires"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("show_sortie_qr", sa.Boolean(), nullable=False, server_default=sa.text("true")))
        batch.add_column(sa.Column("sortie_qr_base_url", sa.String(length=300), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("show_sortie_watermark", sa.Boolean(), nullable=False, server_default=sa.text("true"))
        )
        batch.add_column(sa.Column("sortie_watermark_text", sa.String(length=50), nullable=False, server_default="PAYÉ"))
        batch.add_column(
            sa.Column("sortie_watermark_opacity", sa.Numeric(4, 2), nullable=False, server_default="0.15")
        )


def downgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.drop_column("sortie_watermark_opacity")
        batch.drop_column("sortie_watermark_text")
        batch.drop_column("show_sortie_watermark")
        batch.drop_column("sortie_qr_base_url")
        batch.drop_column("show_sortie_qr")
