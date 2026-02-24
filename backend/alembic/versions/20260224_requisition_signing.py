"""add requisition signing fields

Revision ID: 20260224_requisition_signing
Revises: 20260224_commission_members
Create Date: 2026-02-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260224_requisition_signing"
down_revision = "20260224_commission_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisitions", sa.Column("signed_by_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("requisitions", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_requisitions_signed_by_id", "requisitions", ["signed_by_id"])
    op.create_foreign_key(
        "fk_requisitions_signed_by_id",
        "requisitions",
        "users",
        ["signed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_requisitions_signed_by_id", "requisitions", type_="foreignkey")
    op.drop_index("ix_requisitions_signed_by_id", table_name="requisitions")
    op.drop_column("requisitions", "signed_at")
    op.drop_column("requisitions", "signed_by_id")
