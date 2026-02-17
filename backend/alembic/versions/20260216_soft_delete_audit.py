"""add soft delete fields and audit logs

Revision ID: 20260216_soft_delete_audit
Revises: 20260216_merge_heads_onec
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260216_soft_delete_audit"
down_revision = "20260216_merge_heads_onec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("requisitions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("requisitions", sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_requisitions_is_deleted", "requisitions", ["is_deleted"])

    op.add_column(
        "encaissements",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("encaissements", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("encaissements", sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_encaissements_is_deleted", "encaissements", ["is_deleted"])

    op.add_column(
        "budget_lignes",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("budget_lignes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("budget_lignes", sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_budget_lignes_is_deleted", "budget_lignes", ["is_deleted"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("field_name", sa.String(length=50), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

    op.alter_column("requisitions", "is_deleted", server_default=None)
    op.alter_column("encaissements", "is_deleted", server_default=None)
    op.alter_column("budget_lignes", "is_deleted", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_budget_lignes_is_deleted", table_name="budget_lignes")
    op.drop_column("budget_lignes", "deleted_by")
    op.drop_column("budget_lignes", "deleted_at")
    op.drop_column("budget_lignes", "is_deleted")

    op.drop_index("ix_encaissements_is_deleted", table_name="encaissements")
    op.drop_column("encaissements", "deleted_by")
    op.drop_column("encaissements", "deleted_at")
    op.drop_column("encaissements", "is_deleted")

    op.drop_index("ix_requisitions_is_deleted", table_name="requisitions")
    op.drop_column("requisitions", "deleted_by")
    op.drop_column("requisitions", "deleted_at")
    op.drop_column("requisitions", "is_deleted")
