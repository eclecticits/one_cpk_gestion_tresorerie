"""add service rubriques whitelist

Revision ID: 20260223_service_rubriques
Revises: 20260220_services_module
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260223_service_rubriques"
down_revision = "20260220_services_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("service_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_service_id", "users", ["service_id"])
    op.create_foreign_key("fk_users_service_id", "users", "services", ["service_id"], ["id"])

    op.create_table(
        "service_rubriques",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("budget_poste_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["budget_poste_id"], ["budget_postes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("service_id", "budget_poste_id", name="uq_service_rubrique"),
    )
    op.create_index("ix_service_rubriques_service_id", "service_rubriques", ["service_id"])
    op.create_index("ix_service_rubriques_budget_poste_id", "service_rubriques", ["budget_poste_id"])


def downgrade() -> None:
    op.drop_index("ix_service_rubriques_budget_poste_id", table_name="service_rubriques")
    op.drop_index("ix_service_rubriques_service_id", table_name="service_rubriques")
    op.drop_table("service_rubriques")

    op.drop_constraint("fk_users_service_id", "users", type_="foreignkey")
    op.drop_index("ix_users_service_id", table_name="users")
    op.drop_column("users", "service_id")
