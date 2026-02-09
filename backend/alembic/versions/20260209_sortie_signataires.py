"""add sortie signature fields

Revision ID: 20260209_sortie_signataires
Revises: 20260209_document_sequences
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260209_sortie_signataires"
down_revision = "20260209_document_sequences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("sortie_label_signature", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("sortie_nom_signataire", sa.String(length=200), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.drop_column("sortie_nom_signataire")
        batch.drop_column("sortie_label_signature")
