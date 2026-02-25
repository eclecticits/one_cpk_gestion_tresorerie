"""merge heads drop type_operation

Revision ID: bd2e20e4a9c9
Revises: 20260225_drop_type_operation, 20260225_remove_mini_req
Create Date: 2026-02-25 12:49:48.212527

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd2e20e4a9c9'
down_revision = ('20260225_drop_type_operation', '20260225_remove_mini_req')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
