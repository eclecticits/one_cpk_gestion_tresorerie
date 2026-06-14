"""add reunion composite indexes

Revision ID: 20260604_reunion_idx_lock
Revises: 20260604_sec_reunions
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op


revision = "20260604_reunion_idx_lock"
down_revision = "20260604_sec_reunions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_sec_meetings_org_status_date",
        "secretariat_meetings",
        ["organisation_id", "status", "meeting_date"],
    )
    op.create_index(
        "ix_sec_meeting_part_org_meeting",
        "secretariat_meeting_participants",
        ["organisation_id", "meeting_id"],
    )
    op.create_index(
        "ix_sec_meeting_dec_org_meeting_status",
        "secretariat_meeting_decisions",
        ["organisation_id", "meeting_id", "status"],
    )
    op.create_index(
        "ix_sec_meeting_act_org_meeting_status",
        "secretariat_meeting_action_items",
        ["organisation_id", "meeting_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_sec_meeting_act_org_meeting_status", table_name="secretariat_meeting_action_items")
    op.drop_index("ix_sec_meeting_dec_org_meeting_status", table_name="secretariat_meeting_decisions")
    op.drop_index("ix_sec_meeting_part_org_meeting", table_name="secretariat_meeting_participants")
    op.drop_index("ix_sec_meetings_org_status_date", table_name="secretariat_meetings")
