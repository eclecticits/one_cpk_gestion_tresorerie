"""merge heads after ONEC prefix fix

Revision ID: 20260216_merge_heads_onec
Revises: 20260212_clotures_taux_change, 20260216_fix_prefix_onec
Create Date: 2026-02-16
"""

from alembic import op

revision = "20260216_merge_heads_onec"
down_revision = ("20260212_clotures_taux_change", "20260216_fix_prefix_onec")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
