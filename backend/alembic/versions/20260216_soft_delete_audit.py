"""add soft delete fields and audit logs

Revision ID: 20260216_soft_delete_audit
Revises: 20260216_merge_heads_onec
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260216_soft_delete_audit"
down_revision = "20260216_merge_heads_onec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    def _ensure_soft_delete(table: str, index_name: str) -> None:
        cols = {col["name"] for col in inspector.get_columns(table)}
        if "is_deleted" not in cols:
            op.add_column(
                table,
                sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if "deleted_at" not in cols:
            op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        if "deleted_by" not in cols:
            op.add_column(table, sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True))

        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table, ["is_deleted"])

        op.alter_column(table, "is_deleted", server_default=None)

    _ensure_soft_delete("requisitions", "ix_requisitions_is_deleted")
    _ensure_soft_delete("encaissements", "ix_encaissements_is_deleted")
    _ensure_soft_delete("budget_lignes", "ix_budget_lignes_is_deleted")

    if not inspector.has_table("audit_logs"):
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
