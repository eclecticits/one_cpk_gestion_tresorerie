"""remove mini requisitions type

Revision ID: 20260225_remove_mini_req
Revises: 20260225_merge_status_hist
Create Date: 2026-02-25
"""

from __future__ import annotations

from alembic import op


revision = "20260225_remove_mini_req"
down_revision = "20260225_merge_status_hist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE requisitions
        SET type_requisition = 'classique'
        WHERE LOWER(type_requisition) = 'mini';
        """
    )


def downgrade() -> None:
    pass
