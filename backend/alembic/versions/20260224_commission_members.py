"""add commission members

Revision ID: 20260224_commission_members
Revises: 20260223_service_responsable, 20260223_service_rubriques
Create Date: 2026-02-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260224_commission_members"
down_revision = ("20260223_service_responsable", "20260223_service_rubriques")
branch_labels = None
depends_on = None


def upgrade() -> None:
    role_enum = sa.Enum("PRESIDENT", "DELEGUE", "MEMBRE", "ASSISTANT", name="commission_role_type")

    op.create_table(
        "commission_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role_type", role_enum, nullable=False, server_default="MEMBRE"),
        sa.Column("custom_title", sa.String(length=150), nullable=True),
        sa.Column("is_signer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("service_id", "user_id", "role_type", name="uq_commission_member_role"),
    )
    op.create_index("ix_commission_members_service_id", "commission_members", ["service_id"])
    op.create_index("ix_commission_members_user_id", "commission_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_commission_members_user_id", table_name="commission_members")
    op.drop_index("ix_commission_members_service_id", table_name="commission_members")
    op.drop_table("commission_members")

    role_enum = sa.Enum("PRESIDENT", "DELEGUE", "MEMBRE", "ASSISTANT", name="commission_role_type")
    role_enum.drop(op.get_bind(), checkfirst=True)
