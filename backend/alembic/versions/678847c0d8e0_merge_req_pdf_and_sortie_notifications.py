"""merge req_pdf and sortie_notifications

Revision ID: 678847c0d8e0
Revises: 20260210_req_pdf, 20260211_sortie_notifications
Create Date: 2026-02-11 09:36:44.660332

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '678847c0d8e0'
down_revision = ('20260210_req_pdf', '20260211_sortie_notifications')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
