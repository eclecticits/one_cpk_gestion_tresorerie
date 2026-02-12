"""add date_debut to clotures

Revision ID: 20260212_clotures_date_debut
Revises: 20260212_clotures_caisse
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_clotures_date_debut"
down_revision = "20260212_clotures_caisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clotures", sa.Column("date_debut", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("clotures", "date_debut")
