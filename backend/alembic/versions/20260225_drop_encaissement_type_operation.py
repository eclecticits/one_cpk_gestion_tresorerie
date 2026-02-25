"""drop encaissement type_operation

Revision ID: 20260225_drop_type_operation
Revises: 20260225_merge_status_hist
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260225_drop_type_operation"
down_revision = "20260225_merge_status_hist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("encaissements", "type_operation")


def downgrade() -> None:
    op.add_column(
        "encaissements",
        sa.Column(
            "type_operation",
            sa.String(length=100),
            nullable=False,
            server_default="poste_budgetaire",
        ),
    )
    op.alter_column("encaissements", "type_operation", server_default=None)
