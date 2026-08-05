"""Ajoute la province d'attache aux experts-comptables

Revision ID: 20260802_expert_province
Revises: 20260801_compta_reset_bypass
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_expert_province"
down_revision = "20260801_compta_reset_bypass"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experts_comptables", sa.Column("province_attache", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("experts_comptables", "province_attache")
