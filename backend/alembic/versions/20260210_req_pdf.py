"""add pdf path for requisition

Revision ID: 20260210_req_pdf
Revises: 20260210_smtp_password
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260210_req_pdf"
down_revision = "20260210_smtp_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisitions", sa.Column("pdf_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("requisitions", "pdf_path")
