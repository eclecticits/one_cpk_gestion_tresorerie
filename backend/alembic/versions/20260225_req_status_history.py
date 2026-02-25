"""add requisition status history table

Revision ID: 20260225_req_status_hist
Revises: 20260224_req_status_met
Create Date: 2026-02-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260225_req_status_hist"
down_revision = "20260224_req_status_met"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requisition_status_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_requisition_status_history_requisition_id",
        "requisition_status_history",
        ["requisition_id"],
    )
    op.create_index(
        "ix_requisition_status_history_changed_by",
        "requisition_status_history",
        ["changed_by"],
    )
    op.create_index(
        "ix_requisition_status_history_changed_at",
        "requisition_status_history",
        ["changed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_requisition_status_history_changed_at", table_name="requisition_status_history")
    op.drop_index("ix_requisition_status_history_changed_by", table_name="requisition_status_history")
    op.drop_index("ix_requisition_status_history_requisition_id", table_name="requisition_status_history")
    op.drop_table("requisition_status_history")
