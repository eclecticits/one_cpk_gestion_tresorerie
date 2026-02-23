"""merge heads

Revision ID: f1b0b5ff77bb
Revises: 1f84e099e76b, 20260223_service_rubriques
Create Date: 2026-02-23 12:07:50.513647

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1b0b5ff77bb'
down_revision = ('1f84e099e76b', '20260223_service_rubriques')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
