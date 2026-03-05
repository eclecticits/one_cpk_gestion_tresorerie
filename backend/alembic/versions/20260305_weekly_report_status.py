"""weekly report status fields

Revision ID: 20260305_weekly_report_status
Revises: 20260305_transferts_internes
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260305_weekly_report_status"
down_revision = "20260305_transferts_internes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("last_weekly_report_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_weekly_report_status", sa.String(length=20), nullable=False, server_default="never"),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_weekly_report_error", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "last_weekly_report_error")
    op.drop_column("system_settings", "last_weekly_report_status")
    op.drop_column("system_settings", "last_weekly_report_sent_at")
