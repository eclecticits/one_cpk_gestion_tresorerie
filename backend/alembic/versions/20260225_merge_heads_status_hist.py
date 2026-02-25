"""merge heads for requisition status history

Revision ID: 20260225_merge_status_hist
Revises: 20260224_comm_member_id, 20260225_req_status_hist
Create Date: 2026-02-25
"""

from __future__ import annotations

from alembic import op  # noqa: F401


revision = "20260225_merge_status_hist"
down_revision = ("20260224_comm_member_id", "20260225_req_status_hist")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
