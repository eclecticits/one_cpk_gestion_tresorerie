"""ajout devise sur lignes_requisition

Revision ID: 20260205_req_devise
Revises: 20260205_settings_budget
Create Date: 2026-02-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260205_req_devise"
down_revision = "20260205_settings_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lignes_requisition",
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
    )


def downgrade() -> None:
    op.drop_column("lignes_requisition", "devise")
