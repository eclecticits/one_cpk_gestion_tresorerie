"""merge heads

Revision ID: 0ab0d11a512f
Revises: 20260225_add_exchange_multi, 20260226_add_sortie_annulee_le
Create Date: 2026-02-26 13:24:02.020246

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0ab0d11a512f'
down_revision = ('20260225_add_exchange_multi', '20260226_add_sortie_annulee_le')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
