"""settings and budget metadata

Revision ID: 20260205_settings_budget
Revises: 20260205_sortie_budget
Create Date: 2026-02-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260205_settings_budget"
down_revision = "20260205_sortie_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("default_currency", sa.String(length=3), nullable=False, server_default="USD"))
        batch.add_column(sa.Column("secondary_currency", sa.String(length=3), nullable=False, server_default="CDF"))
        batch.add_column(sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=False, server_default="0"))
        batch.add_column(sa.Column("fiscal_year", sa.Integer(), nullable=False, server_default="2026"))
        batch.add_column(sa.Column("budget_alert_threshold", sa.Integer(), nullable=False, server_default="80"))
        batch.add_column(sa.Column("budget_block_overrun", sa.Boolean(), nullable=False, server_default=sa.text("true")))
        batch.add_column(sa.Column("budget_force_roles", sa.String(length=300), nullable=False, server_default=""))

    with op.batch_alter_table("budget_lignes") as batch:
        batch.add_column(sa.Column("parent_code", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    op.create_table(
        "budget_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exercice_id", sa.Integer(), sa.ForeignKey("budget_exercices.id"), nullable=True),
        sa.Column("budget_ligne_id", sa.Integer(), sa.ForeignKey("budget_lignes.id"), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("field_name", sa.String(length=50), nullable=False),
        sa.Column("old_value", sa.Numeric(15, 2), nullable=True),
        sa.Column("new_value", sa.Numeric(15, 2), nullable=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("budget_audit_logs")

    with op.batch_alter_table("budget_lignes") as batch:
        batch.drop_column("active")
        batch.drop_column("parent_code")

    with op.batch_alter_table("print_settings") as batch:
        batch.drop_column("budget_force_roles")
        batch.drop_column("budget_block_overrun")
        batch.drop_column("budget_alert_threshold")
        batch.drop_column("fiscal_year")
        batch.drop_column("exchange_rate")
        batch.drop_column("secondary_currency")
        batch.drop_column("default_currency")
