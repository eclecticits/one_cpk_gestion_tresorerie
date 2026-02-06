"""ajout role_menu_permissions

Revision ID: 20260205_role_perm
Revises: 20260205_req_budget
Create Date: 2026-02-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260205_role_perm"
down_revision = "20260205_req_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_menu_permissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("menu_name", sa.String(length=80), nullable=False),
        sa.Column("can_access", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "menu_name", name="uq_role_menu_permissions_role_menu"),
    )
    op.create_index("ix_role_menu_permissions_role", "role_menu_permissions", ["role"])
    op.create_index("ix_role_menu_permissions_menu_name", "role_menu_permissions", ["menu_name"])


def downgrade() -> None:
    op.drop_index("ix_role_menu_permissions_menu_name", table_name="role_menu_permissions")
    op.drop_index("ix_role_menu_permissions_role", table_name="role_menu_permissions")
    op.drop_table("role_menu_permissions")
