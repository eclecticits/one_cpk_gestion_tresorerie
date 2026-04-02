"""add pdf_path to remboursements_transport

Revision ID: 20260401_remboursement_pdf_path
Revises: 20260331_recu_numero_padding_fix
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260401_remboursement_pdf_path"
down_revision = "20260331_recu_numero_padding_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remboursements_transport", sa.Column("pdf_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("remboursements_transport", "pdf_path")
