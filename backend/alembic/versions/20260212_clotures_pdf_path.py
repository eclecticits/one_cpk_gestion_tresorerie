"""add pdf path to clotures

Revision ID: 20260212_clotures_pdf_path
Revises: 20260212_clotures_date_debut
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_clotures_pdf_path"
down_revision = "20260212_clotures_date_debut"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clotures", sa.Column("pdf_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("clotures", "pdf_path")
