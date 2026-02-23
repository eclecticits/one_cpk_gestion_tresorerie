"""merge heads budget snapshots and services

Revision ID: 1f84e099e76b
Revises: 20260217_budget_poste_snapshots, 20260220_services_module
Create Date: 2026-02-20 23:26:41.174702

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f84e099e76b'
down_revision = ('20260217_budget_poste_snapshots', '20260220_services_module')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
