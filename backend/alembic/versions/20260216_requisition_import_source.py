"""add requisition import source

Revision ID: 20260216_import_src
Revises: 20260216_soft_delete_audit
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260216_import_src"
down_revision = "20260216_soft_delete_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisitions", sa.Column("import_source", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("requisitions", "import_source")
