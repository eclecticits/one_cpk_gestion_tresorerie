"""merge heads

Revision ID: 0006_merge_heads
Revises: 0005_requisitions_tables, 0005_validate_enc_constraints, 20250201_remb_transport
Create Date: 2026-01-29 00:00:00.000000
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0006_merge_heads"
down_revision = (
    "0005_requisitions_tables",
    "0005_validate_enc_constraints",
    "20250201_remb_transport",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
