"""Add icon and sort_order to organisations.

Revision ID: 20260322_org_icon_order
Revises: 20260321_banques_tenant_scope
Create Date: 2026-03-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_org_icon_order"
down_revision = "20260321_banques_tenant_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organisations", sa.Column("icon", sa.String(length=20), nullable=True, server_default="🏢"))
    op.add_column("organisations", sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"))
    op.create_index("ix_organisations_sort_order", "organisations", ["sort_order"])
    op.execute("UPDATE organisations SET icon = '🏢' WHERE icon IS NULL")
    op.execute("UPDATE organisations SET sort_order = 0 WHERE sort_order IS NULL")
    op.alter_column("organisations", "sort_order", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_organisations_sort_order", table_name="organisations")
    op.drop_column("organisations", "sort_order")
    op.drop_column("organisations", "icon")
