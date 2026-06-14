"""add hr configurable references

Revision ID: 20260528_hr_refs
Revises: 20260528_hr_mvp
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_hr_refs"
down_revision = "20260528_hr_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_references",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("libelle", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "category", "code", name="uq_hr_references_tenant_category_code"),
    )
    op.create_index(op.f("ix_hr_references_tenant_id"), "hr_references", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_hr_references_category"), "hr_references", ["category"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_hr_references_category"), table_name="hr_references")
    op.drop_index(op.f("ix_hr_references_tenant_id"), table_name="hr_references")
    op.drop_table("hr_references")
