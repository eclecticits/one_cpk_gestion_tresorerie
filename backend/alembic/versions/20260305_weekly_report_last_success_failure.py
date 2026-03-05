"""weekly report success/failure timestamps

Revision ID: 20260305_weekly_report_last_sf
Revises: 20260305_weekly_report_status
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260305_weekly_report_last_sf"
down_revision = "20260305_weekly_report_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("last_weekly_report_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_weekly_report_failure_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "last_weekly_report_failure_at")
    op.drop_column("system_settings", "last_weekly_report_success_at")
