"""Add hr_payroll_settings table (configurable IPR/CNSS parameters per org)

Revision ID: 20260702_hr_payroll_settings
Revises: 20260702_hr_ipr_cnss
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260702_hr_payroll_settings"
down_revision = "20260702_hr_ipr_cnss"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_payroll_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("devise_bareme", sa.String(length=3), nullable=False, server_default="CDF"),
        sa.Column("ipr_brackets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ipr_plancher", sa.Numeric(14, 2), nullable=False),
        sa.Column("ipr_plafond_taux", sa.Numeric(5, 4), nullable=False),
        sa.Column("cnss_taux_salarie", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_hr_payroll_settings_tenant"),
    )
    op.create_index(
        "ix_hr_payroll_settings_tenant_id", "hr_payroll_settings", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_hr_payroll_settings_tenant_id", table_name="hr_payroll_settings")
    op.drop_table("hr_payroll_settings")
