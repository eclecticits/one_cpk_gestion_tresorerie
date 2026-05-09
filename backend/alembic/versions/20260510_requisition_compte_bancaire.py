"""Add bank account choice on requisitions.

Revision ID: 20260510_req_bank
Revises: 20260509_tenant_strict_scope
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_req_bank"
down_revision = "20260509_tenant_strict_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisitions", sa.Column("compte_bancaire_id", sa.Integer(), nullable=True))
    op.create_index("ix_requisitions_compte_bancaire_id", "requisitions", ["compte_bancaire_id"])
    op.create_foreign_key(
        "fk_requisitions_compte_bancaire_id",
        "requisitions",
        "comptes_bancaires",
        ["compte_bancaire_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_requisitions_compte_bancaire_id", "requisitions", type_="foreignkey")
    op.drop_index("ix_requisitions_compte_bancaire_id", table_name="requisitions")
    op.drop_column("requisitions", "compte_bancaire_id")
